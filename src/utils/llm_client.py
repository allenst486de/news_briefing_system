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
from typing import List, Optional, Tuple, Union

import requests

from .logger import setup_logger

logger = setup_logger()

NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NVIDIA_MODEL = "google/gemma-4-31b-it"  # NVIDIA NIM 카탈로그에서 모델 폐기/변경 시 갱신 필요

# ── 클라우드 모델 사다리 ──────────────────────────────────────────────────
# 2026-09-18부터 나흘 연속 번역·시사용어가 무너졌다. 키도 계정도 멀쩡했고, gemma-4-31b-it
# 한 모델만 NVIDIA 무료 서버의 대기열이 밀렸다. 9/21 실측: "hi" 한 줄도 대기열에서
# 239~300초를 기다렸고 생성은 1~2초, 기사 8건 청크는 대기 122초 + 생성 64초.
# 대기가 300초를 넘으면 NVIDIA 게이트웨이가 504로 끊는다. 밀림은 들쭉날쭉해서 한 시간
# 뒤에는 27~43초로 정상이었다. 우리 타임아웃은 180초 × 3회라 막힌 날엔 청크마다 9분씩
# 허공에 쓰고 전부 로컬로 넘겼다 — 모델 하나에 목을 매지 않고 사다리를 둔다.
#
# 9/21 같은 프롬프트(실제 요약 청크, 기사 17건)로 비교한 후보:
#   gemma-4-31b-it          기준. 원문에 없는 내용을 덧붙이지 않음 · 번역 정확
#   muse-glimmer-30b        gemma와 가장 비슷 — 원문 밖 내용을 거의 안 붙임 · 9~55초.
#                           대신 영어 이름·단어를 번역 안 하고 남기거나 오역이 가끔 있음
#                           ('아이티 대통령'을 요약 한 곳에서 '자메이카'로)
#   deepseek-v4-flash-0731  문장은 매끄럽지만 원문에 없는 배경·반응을 지어 붙임 · 76~119초
#   nemotron-3-ultra-550b   가장 매끄럽지만 지어 붙이는 게 가장 많음('메르츠'→'메르켈',
#                           '시민 의견이 엇갈렸다' 창작) → 쓰지 않음
#   gemma-3 12b/4b 등 다른 gemma는 NVIDIA에서 내려감(404)
# 뉴스 요약은 '원문에 없는 내용 금지'가 우선이라 충실한 순서로 둔다:
#   gemma → muse-glimmer → deepseek → (로컬 gemma-qat) → 규칙기반
# LLM_CLOUD_MODELS / LLM_LAST_RESORT_MODELS(쉼표 구분)로 바꿀 수 있다. 빈 값이면 끈다.
# 2026-09-25: deepseek-v4-flash-0731이 410(수명 종료)으로 내려가 후속 deepseek-v4.1-flash로 교체.
# 같은 기사 17건 비교에서 원문 충실도·고유명사 정확도가 muse-glimmer 이상이었다.
_DEFAULT_CLOUD_FALLBACKS = ["meta/muse-glimmer-30b", "deepseek-ai/deepseek-v4.1-flash"]
_DEFAULT_LAST_RESORT = []

# 응답 대기(읽기) 상한. gemma는 붐비면 대기열에서 헤더 없이 서 있다가 차례가 오면
# 금방 끝낸다. 대기열이 밀린 날에도 239~300초 사이에 응답이 오는 경우가 있었고,
# 300초를 넘기면 어차피 NVIDIA가 504로 끊으므로 그 직후까지 기다린다.
# 대체 모델은 생성 자체가 길 수 있어(deepseek 해외+상세 182초) 넉넉히 준다.
_MODEL_READ_TIMEOUT = {NVIDIA_MODEL: 310}
_DEFAULT_READ_TIMEOUT = 300
_CONNECT_TIMEOUT = 10


def _model_list(env_name: str, default: List[str]) -> List[str]:
    raw = os.getenv(env_name)
    if raw is None:
        return list(default)
    return [m.strip() for m in raw.split(",") if m.strip()]


def cloud_models() -> List[str]:
    """주력 사다리: 앞에서부터 쓰고, 막힌 모델은 건너뛴다. 맨 앞은 항상 NVIDIA_MODEL."""
    rest = [m for m in _model_list("LLM_CLOUD_MODELS", _DEFAULT_CLOUD_FALLBACKS) if m != NVIDIA_MODEL]
    return [NVIDIA_MODEL] + rest


def last_resort_models() -> List[str]:
    """로컬까지 실패했을 때만 부르는 모델. 기본은 없음(지어 붙이는 모델을 쓰느니 원문을 싣는다)."""
    return _model_list("LLM_LAST_RESORT_MODELS", _DEFAULT_LAST_RESORT)


class _ModelHealth:
    """
    모델별 회로 차단기. 한 모델이 연달아 실패하면 한동안 그 모델을 건너뛴다.

    없으면 막힌 모델에 동시 호출 16개가 계속 줄을 서서 각자 타임아웃까지 기다린다
    (9/18: 청크마다 180초 × 3회). 차단 중에도 COOLDOWN이 지나면 호출 하나만 시험 삼아
    보내고(half-open), 그게 성공하면 다시 연다 — 대기열이 풀리면 좋은 모델로 돌아온다.
    """
    FAIL_THRESHOLD = 3
    COOLDOWN = 600

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._state = {}

    def _get(self, model):
        return self._state.setdefault(model, {"streak": 0, "open_until": 0.0, "trial": False,
                                              "ok": 0, "fail": 0, "why": ""})

    def try_acquire(self, model: str) -> bool:
        with self._lock:
            st = self._get(model)
            if not st["open_until"]:
                return True
            if st["trial"] or self._clock() < st["open_until"]:
                return False
            st["trial"] = True          # 시험 호출 하나만 통과시킨다
            return True

    def success(self, model: str) -> None:
        with self._lock:
            st = self._get(model)
            reopened = bool(st["open_until"])
            st.update(streak=0, open_until=0.0, trial=False)
            st["ok"] += 1
        if reopened:
            logger.info(f"[{model}] 시험 호출 성공 — 다시 주력으로 씀")

    def failure(self, model: str, why: str) -> None:
        with self._lock:
            st = self._get(model)
            st["streak"] += 1
            st["fail"] += 1
            st["why"] = why
            if st["trial"]:
                st["trial"] = False
                st["open_until"] = self._clock() + self.COOLDOWN
                logger.warning(f"[{model}] 시험 호출도 실패({why}) — {self.COOLDOWN}초 더 건너뜀")
            elif not st["open_until"] and st["streak"] >= self.FAIL_THRESHOLD:
                st["open_until"] = self._clock() + self.COOLDOWN
                logger.warning(f"[{model}] 연속 {st['streak']}회 실패({why}) — "
                               f"{self.COOLDOWN}초 동안 다음 모델로 우회")

    def kill(self, model: str, why: str) -> None:
        """모델이 내려간 경우(404/410) — 이번 실행 내내 쓰지 않는다."""
        with self._lock:
            st = self._get(model)
            st.update(open_until=float("inf"), trial=False, why=why)
            st["fail"] += 1
        logger.warning(f"[{model}] 사용 불가({why}) — 이번 실행에서 제외")

    def report(self) -> str:
        with self._lock:
            used = [(m, s) for m, s in self._state.items() if s["ok"] or s["fail"]]
            return " · ".join(f"{m.split('/')[-1]} 성공 {s['ok']}/실패 {s['fail']}" for m, s in used)


_health = _ModelHealth()


def reset_model_health() -> None:
    """테스트용 — 앞 테스트가 연 차단기가 뒤 테스트에 새지 않게."""
    global _health
    _health = _ModelHealth()


# ── 로컬 LLM 폴백 티어 ────────────────────────────────────────────────────
# 클라우드 호출이 실패한 청크만 로컬 모델이 받아낸다. 예전에는 클라우드가 실패하면
# 곧장 규칙기반으로 떨어져 지면에 영문 원문이 그대로 노출됐다 — 그날 API 사정에 따라
# 폴백률이 0~26%로 튀었다. 로컬에 같은 계열 모델(gemma-4-31b-qat)을 두면 클라우드가
# 죽어도 품질이 유지된다. 느릴 뿐이고, 로컬 실행이라 30분 하드 제한이 없다.
#
# 실측(M4 Pro 48GB, 기사 8건 청크 1회):
#   NVIDIA 클라우드 gemma-4-31b   약 87초
#   로컬 gemma-4-31b-qat          약 277초  ← 같은 품질, 3배 느림
#   로컬 gpt-oss-20b(minimal)     약 19초   ← 빠르지만 고유명사 오역·환각으로 부적합
# 전부를 로컬로 돌리면 5시간이라 주력으로는 못 쓴다. '실패한 청크만' 받는 안전망이다.
# 주의: 이 설정들은 반드시 '호출 시점'에 환경변수를 읽어야 한다. 모듈 수준에서
# os.getenv로 굳혀두면 안 된다 — main.py가 load_dotenv()를 import 뒤에 부르기
# 때문에, import 시점에는 .env가 아직 로드되지 않아 값이 전부 기본값으로 굳는다.
# (NVIDIA_API_KEY가 call_llm 안에서 os.getenv로 읽히는 것도 같은 이유다.)
_DEFAULT_LOCAL_URL = "http://localhost:1234/v1/chat/completions"
_DEFAULT_LOCAL_MODEL = "google/gemma-4-31b-qat"


def local_llm_enabled() -> bool:
    return os.getenv("LOCAL_LLM_ENABLED", "1") not in ("0", "false", "False", "")


def local_llm_model() -> str:
    return os.getenv("LOCAL_LLM_MODEL", _DEFAULT_LOCAL_MODEL)


def _local_llm_url() -> str:
    return os.getenv("LOCAL_LLM_URL", _DEFAULT_LOCAL_URL)


def _local_llm_timeout() -> int:
    # 실측 277초 — 콜드스타트(모델 로드)까지 겹치면 더 걸리므로 넉넉히 잡는다.
    return int(os.getenv("LOCAL_LLM_TIMEOUT", "900"))


# 로컬은 통합 메모리 대역폭에 묶여 동시 호출을 늘려도 총 처리량이 거의 안 는다
# (실측: 단일 48.8 tok/s → 4병렬 집계 57.5 tok/s, +18%뿐). 오히려 개별 호출이
# 늘어져 타임아웃 위험만 커지므로 직렬에 가깝게 유지한다.
# 세마포어도 첫 사용 시점에 만든다 — 위와 같은 .env 로드 순서 문제 때문.
_local_slot = None
_local_slot_lock = threading.Lock()


def _get_local_slot() -> threading.Semaphore:
    global _local_slot
    with _local_slot_lock:
        if _local_slot is None:
            limit = int(os.getenv("LOCAL_LLM_CONCURRENCY", "2"))
            _local_slot = threading.Semaphore(limit)
            logger.info(f"Local LLM concurrency set to {limit}")
        return _local_slot

# LLM이 실패해도 항상 규칙기반으로 조용히 폴백하기 때문에, 며칠씩 "번역이 안 된다"를
# 모르고 지나가는 일이 실제로 있었다. 실행마다 집계해서 main.py가 Actions 실행 요약에
# 찍는다 — 다음 실행에서 원인을 바로 볼 수 있도록.
LLM_STATS = {
    "calls": 0, "ok": 0, "no_key": 0, "http_error": 0,
    "network_error": 0, "parse_fail": 0, "salvaged": 0, "budget": 0,
    # 로컬 폴백 티어가 클라우드 실패를 몇 건이나 건져냈는지. local_ok가 꾸준히
    # 잡히면 클라우드 키 상태를 점검해야 한다는 신호다.
    "local_ok": 0, "local_fail": 0, "local_budget": 0,
    "errors": [],
}

_stats_lock = threading.Lock()

# 클라우드 LLM이 실행 전체에서 쓸 수 있는 총 시간. 초과하면 남은 호출은 즉시
# None을 반환하고 호출부가 (로컬 폴백 → 규칙기반으로) 넘어간다 — 요약 품질이
# 일부 떨어져도 사이트는 반드시 발행된다.
#
# 예전에는 900초였다. 워크플로 30분 하드 제한 안에서 수집·본문(약 4분)과
# HTML·텔레그램(약 2분)까지 끝나야 했기 때문이다(실측 실행 시간이 8.9/15.2/26.9분
# 으로 편차가 커서, 26.9분짜리는 30분 벽까지 3분밖에 안 남았다).
# 로컬 맥 실행으로 옮기면서 그 하드 제한이 사라져 1800초로 올렸다 — 예산에 쫓겨
# 규칙기반으로 떨어지는 일이 줄어든다. 무한정 도는 것만 막는 상한이다.
#
# 환경변수로 빼지 않는다: 이 모듈은 main.py의 load_dotenv()보다 먼저 import되므로
# 모듈 수준 os.getenv는 .env를 못 읽고 조용히 기본값으로 굳는다. 바꾸려면 이 값을
# 직접 수정할 것. (test_salvage.py가 이 속성을 덮어써서 예산 소진을 검증한다)
LLM_TIME_BUDGET_SECONDS = 1800
_deadline = None

# 로컬 폴백은 청크당 약 277초라 클라우드와 같은 예산을 쓰면 두세 건 만에 소진된다.
# 별도 예산을 준다 — 폴백률 20%(약 15청크) × 277초 ≈ 70분을 감당할 수 있는 값.
_local_deadline = None

# 429 재시도 대기(초). Retry-After 헤더가 있으면 그쪽이 우선.
_RATE_LIMIT_BACKOFF = [5, 15]
_RATE_LIMIT_MAX_WAIT = 30

# 전체 동시 요청 상한. 카테고리 8개 × 청크 워커를 곱하면 20개가 넘게 붙는데,
# 살아있는 키가 하나뿐이면 그게 전부 한 계정의 rate limit으로 몰린다.
# 실제로 쓸 수 있는 키 개수를 확인한 뒤 set_concurrency()로 조정한다.
_PER_KEY_CONCURRENCY = 2
_MIN_CONCURRENT, _MAX_CONCURRENT = 3, 16
_slot = threading.Semaphore(_MIN_CONCURRENT)


def set_concurrency(working_keys: int) -> int:
    """쓸 수 있는 키 개수에 맞춰 전체 동시 호출 수를 정한다. 요약 시작 전에만 호출."""
    global _slot
    limit = max(_MIN_CONCURRENT, min(working_keys * _PER_KEY_CONCURRENCY, _MAX_CONCURRENT))
    _slot = threading.Semaphore(limit)
    logger.info(f"LLM concurrency set to {limit} (working keys: {working_keys})")
    return limit

# 키별 상태 — 실행 시작 시 probe_key로 채우고 실행 요약에 찍는다
KEY_STATUS = {}


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


def local_llm_time_budget() -> int:
    return int(os.getenv("LOCAL_LLM_TIME_BUDGET_SECONDS", "5400"))


def _local_budget_exhausted() -> bool:
    """로컬 티어 전용 예산. 클라우드 예산과 독립적으로 흐른다."""
    global _local_deadline
    if _local_deadline is None:
        _local_deadline = time.monotonic() + local_llm_time_budget()
        return False
    return time.monotonic() > _local_deadline


def reserve_budget(seconds: int) -> None:
    """
    지금부터 최소 seconds초는 클라우드·로컬 모두 부를 수 있게 마감을 늦춘다.

    예산은 실행 전체가 나눠 쓰는 스톱워치라, 기사 요약이 느린 날에는 맨 뒤에 붙은
    Top10 선정·시사용어 추출이 호출해 보지도 못하고 None을 받았다(9/18~9/21 나흘 연속
    '시사용어 추출 실패'). 뒤 단계는 호출 몇 건뿐이니 요약이 끝난 뒤 따로 몫을 준다.
    """
    now = time.monotonic()
    for name in ("_deadline", "_local_deadline"):
        current = globals()[name]
        if current is None or current - now < seconds:
            globals()[name] = now + seconds
    logger.info(f"LLM 예산: 마무리 단계용으로 {seconds}초 확보")


def stats_summary() -> str:
    s = LLM_STATS
    if local_llm_enabled():
        local_line = (
            f"로컬 폴백: 성공 {s['local_ok']} · 실패 {s['local_fail']} · "
            f"예산초과 {s['local_budget']} (모델 {local_llm_model()})"
        )
    else:
        local_line = "로컬 폴백: 비활성"

    lines = [
        f"호출 {s['calls']}건 · 성공 {s['ok']} · 부분복구 {s['salvaged']} · "
        f"JSON실패 {s['parse_fail']} · HTTP오류 {s['http_error']} · "
        f"네트워크오류 {s['network_error']} · 키없음 {s['no_key']} · "
        f"시간예산초과 {s['budget']}",
        local_line,
    ]
    models = _health.report()
    if models:
        lines.append(f"모델별: {models}")
    if s["errors"]:
        lines.append("첫 오류: " + s["errors"][0])
    return "\n".join(lines)


def call_local_llm(system_prompt: str, user_prompt: str, *, temperature: float = 0.3,
                   max_tokens: int = 4096) -> Optional[str]:
    """
    로컬 OpenAI 호환 서버(LM Studio 등)에 1회 호출. 클라우드가 실패한 청크만 온다.

    실패해도 예외를 던지지 않고 None을 반환한다 — LM Studio가 꺼져 있거나 모델이
    안 올라와 있어도 파이프라인은 규칙기반으로 계속 간다. 로컬이 '있으면 좋은
    안전망'이지 필수 의존이 되어서는 안 된다.

    재시도는 하지 않는다. 호출 하나가 약 277초라 재시도하면 예산만 태운다.
    """
    if not local_llm_enabled():
        return None
    if _local_budget_exhausted():
        _record("local_budget",
                f"로컬 LLM 시간 예산 {local_llm_time_budget()}초 초과")
        return None

    payload = {
        "model": local_llm_model(),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
        # 클라우드 경로와 동일하게 thinking을 끈다. 켜져 있으면 추론 텍스트가
        # max_tokens를 다 먹고 content가 빈 채로 끝난다(nemotron 실측: 추론
        # 24,883자 / 본문 0자 / finish_reason=length).
        "chat_template_kwargs": {"enable_thinking": False},
    }

    try:
        # 로컬은 대역폭이 병목이라 동시 호출을 좁게 제한한다
        with _get_local_slot():
            # 예산은 슬롯을 잡은 뒤 한 번 더 본다. 카테고리 8개 × 청크 워커가
            # 한꺼번에 몰리면 20개가 넘는 스레드가 진입 시점에 전부 예산 검사를
            # 통과해버리고, 그 뒤 슬롯 2개로 몇 시간을 직렬로 소화한다 —
            # 대기 중에 예산이 끝나도 아무도 멈추지 않는다.
            if _local_budget_exhausted():
                _record("local_budget",
                        f"로컬 LLM 시간 예산 {local_llm_time_budget()}초 초과(대기 중)")
                return None
            resp = requests.post(_local_llm_url(), json=payload,
                                 timeout=_local_llm_timeout())
    except Exception as e:
        logger.warning(f"Local LLM call failed: {type(e).__name__}: {e}")
        _record("local_fail", f"로컬 LLM {type(e).__name__}: {str(e)[:150]}")
        return None

    if not resp.ok:
        logger.warning(f"Local LLM rejected ({resp.status_code}): {resp.text[:300]}")
        _record("local_fail", f"로컬 LLM HTTP {resp.status_code}: {resp.text[:150]}")
        return None

    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError, TypeError) as e:
        _record("local_fail", f"로컬 LLM 응답 형식 이상: {type(e).__name__}")
        return None

    if not content:
        # thinking 모델을 지정했을 때 content가 비고 reasoning만 오는 경우
        _record("local_fail", "로컬 LLM 응답 content가 비어 있음(thinking 모델?)")
        return None

    logger.info("Local LLM fallback succeeded")
    _record("local_ok")
    return content


def call_llm(system_prompt: str, user_prompt: str, *, temperature: float = 0.3,
             max_tokens: int = 4096, timeout: int = 180, retries: int = 2,
             api_key: Optional[str] = None) -> Optional[str]:
    """
    LLM 호출 사다리:
      클라우드(gemma → muse-glimmer → deepseek, 막힌 모델은 건너뜀) → 로컬
      → 최후 수단 모델(기본 없음, 환경변수로만 켬) → None

    클라우드를 주력으로 두는 이유는 속도다(청크당 87초 대 277초). 로컬은 클라우드가
    모두 실패한 청크만 받아 같은 품질(gemma)을 유지시키는 안전망이다.

    호출부는 이 함수가 None을 주면 규칙기반으로 넘어간다(기존과 동일).
    """
    with _stats_lock:
        LLM_STATS["calls"] += 1

    kwargs = dict(temperature=temperature, max_tokens=max_tokens, timeout=timeout,
                  retries=retries, api_key=api_key)
    content, stop = _cloud_chain(system_prompt, user_prompt, cloud_models(), **kwargs)
    if content is not None:
        return content

    # 클라우드가 어떤 이유로든(키 없음·429·4xx·타임아웃·예산 초과) 못 만들어냈다
    content = call_local_llm(
        system_prompt, user_prompt, temperature=temperature, max_tokens=max_tokens,
    )
    if content is not None:
        return content

    # 429(계정 단위 호출 제한)·키 문제·예산 소진이면 다른 모델을 불러도 똑같다
    last = last_resort_models()
    if last and stop is None and not _budget_exhausted():
        content, _ = _cloud_chain(system_prompt, user_prompt, last, **kwargs)
        if content is not None:
            logger.info(f"최후 수단 모델로 건짐 ({','.join(last)})")
    return content


def _call_cloud_llm(system_prompt: str, user_prompt: str, **kwargs) -> Optional[str]:
    """주력 사다리만 부른다(로컬·최후 수단 없이). 기존 호출부 호환용."""
    return _cloud_chain(system_prompt, user_prompt, cloud_models(), **kwargs)[0]


def _cloud_chain(system_prompt: str, user_prompt: str, models: List[str], *,
                 temperature: float = 0.3, max_tokens: int = 4096, timeout: int = 180,
                 retries: int = 2, api_key: Optional[str] = None
                 ) -> Tuple[Optional[str], Optional[str]]:
    """
    models를 앞에서부터 한 번씩 불러 처음 성공한 응답을 준다. (본문, 중단 사유)
    중단 사유가 있으면(예산·키·429) 뒤 단계에서도 클라우드를 더 부르지 않는다.
    """
    if _budget_exhausted():
        _record("budget", f"LLM 시간 예산 {LLM_TIME_BUDGET_SECONDS}초 초과 — 남은 요약은 로컬/규칙기반")
        return None, "budget"

    api_key = api_key or os.getenv("NVIDIA_API_KEY")
    if not api_key:
        logger.warning("NVIDIA_API_KEY not set — skipping LLM call")
        _record("no_key", "NVIDIA_API_KEY 환경변수가 비어 있음")
        return None, "no_key"

    tried = False
    for model in models:
        if not _health.try_acquire(model):
            continue
        if tried and _budget_exhausted():
            _record("budget", f"LLM 시간 예산 {LLM_TIME_BUDGET_SECONDS}초 초과 — 남은 요약은 로컬/규칙기반")
            return None, "budget"
        tried = True
        outcome, content = _call_model(model, system_prompt, user_prompt, api_key,
                                       temperature=temperature, max_tokens=max_tokens,
                                       timeout=timeout, retries=retries)
        if outcome == "ok":
            return content, None
        if outcome in ("rate_limited", "bad_key"):
            return None, outcome
        # "fail" — 다음 모델로

    if not tried:
        _record("circuit_open", "클라우드 모델이 전부 차단 중 — 로컬로 넘김")
    return None, None


def _call_model(model: str, system_prompt: str, user_prompt: str, api_key: str, *,
                temperature: float, max_tokens: int, timeout: int, retries: int
                ) -> Tuple[str, Optional[str]]:
    """
    모델 하나를 비스트리밍으로 1회 호출. ("ok"|"fail"|"rate_limited"|"bad_key", 본문)

    같은 모델 재시도는 429일 때만 한다. 타임아웃·5xx에 같은 모델을 다시 부르면
    막힌 대기열에 또 줄을 서는 것뿐이라(9/18: 180초 × 3회) 곧장 다음 모델로 넘긴다.

    timeout 기본값 주의: 기사 8건 배치는 한국어 요약 3,500토큰가량을 생성해
    호출 하나가 90초 안팎 걸린다. 모델별 읽기 상한(_MODEL_READ_TIMEOUT)과 호출부가
    준 timeout 중 큰 값을 쓴다.
    """
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "model": model,
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
    read_timeout = max(timeout, _MODEL_READ_TIMEOUT.get(model, _DEFAULT_READ_TIMEOUT))
    short = model.split("/")[-1]

    for attempt in range(retries + 1):
        try:
            # 세마포어는 POST 구간만 잡는다 — 백오프 sleep 동안 붙잡고 있으면
            # 다른 스레드가 빈 슬롯을 못 쓴다
            with _slot:
                resp = requests.post(NVIDIA_API_URL, headers=headers, json=payload,
                                     timeout=(_CONNECT_TIMEOUT, read_timeout))
        except Exception as e:
            logger.warning(f"[{short}] LLM call failed: {type(e).__name__}: {str(e)[:200]}")
            _record("network_error", f"{short} {type(e).__name__}: {str(e)[:200]}")
            _health.failure(model, type(e).__name__)
            return "fail", None

        if resp.status_code == 429:
            # 병렬 호출 중이라 rate limit이 실제로 걸린다. 1~2초 후 재시도하면
            # 대개 또 걸리므로 서버가 알려주는 Retry-After를 우선 따른다.
            if attempt >= retries:
                logger.warning("LLM rate limited (429) — out of retries")
                _record("http_error", "HTTP 429: rate limited (재시도 소진)")
                return "rate_limited", None
            wait = _retry_after_seconds(resp) or _RATE_LIMIT_BACKOFF[min(attempt, len(_RATE_LIMIT_BACKOFF) - 1)]
            logger.warning(f"LLM rate limited (429) — waiting {wait}s")
            time.sleep(wait)
            continue
        if resp.status_code in (401, 403):
            logger.warning(f"[{short}] 키 인증 거절({resp.status_code})")
            _record("http_error", f"HTTP {resp.status_code}: {resp.text[:200]}")
            return "bad_key", None
        if resp.status_code == 410:
            # 410은 수명 종료(모델 폐기) — 이번 실행 내내 쓰지 않는다
            _record("http_error", f"{short} HTTP 410: {resp.text[:200]}")
            _health.kill(model, "HTTP 410")
            return "fail", None
        if resp.status_code == 404:
            # 404는 NVIDIA 쪽 순간 장애일 때도 나온다(9/25 muse-glimmer: 시작 직후 404 → 30초 뒤 정상).
            # 폐기로 단정하지 않고 차단기에 맡긴다 — 계속 404면 연속 실패로 차단된다.
            _record("http_error", f"{short} HTTP 404: {resp.text[:200]}")
            _health.failure(model, "HTTP 404")
            return "fail", None
        if not resp.ok:
            # 5xx·400·422 — 이 모델로는 이 요청을 못 받는다. 다음 모델로
            logger.warning(f"[{short}] LLM call rejected ({resp.status_code}): {resp.text[:300]}")
            _record("http_error", f"{short} HTTP {resp.status_code}: {resp.text[:200]}")
            _health.failure(model, f"HTTP {resp.status_code}")
            return "fail", None

        try:
            content = resp.json()["choices"][0]["message"].get("content")
        except (KeyError, IndexError, ValueError, TypeError, AttributeError) as e:
            _record("http_error", f"{short} 응답 형식 이상: {type(e).__name__}")
            _health.failure(model, "응답 형식 이상")
            return "fail", None
        if not content:
            # thinking이 안 꺼지는 모델은 추론만 채우고 본문을 비운 채 끝난다
            _record("http_error", f"{short} 응답 content가 비어 있음")
            _health.failure(model, "빈 응답")
            return "fail", None

        _record("ok")
        _health.success(model)
        return "ok", content

    return "fail", None


def _retry_after_seconds(resp) -> Optional[int]:
    """429 응답의 Retry-After(초 단위 정수형만) — 없거나 이상하면 None."""
    raw = resp.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(1, min(int(float(raw)), _RATE_LIMIT_MAX_WAIT))
    except (TypeError, ValueError):
        return None


PROBE_TIMEOUT = 120
# 키를 '못 쓴다'고 단정할 수 있는 응답만 나열한다. 타임아웃은 여기 없다 —
# NIM은 모델 인스턴스가 식어 있으면 첫 요청에서 모델을 올리느라 수십 초가 걸리고,
# 그걸 죽은 키로 판정하면 멀쩡한 키를 버리게 된다(실제로 8개 중 7개를 버렸다).
_FATAL_KEY_STATUSES = (400, 401, 403, 404)


def probe_key(api_key: Optional[str], label: str) -> bool:
    """
    키 하나를 최소 호출로 찔러 보고 상태를 KEY_STATUS[label]에 남긴다(출력 8토큰).
    카테고리별 키를 8개 쓰게 되면서, 하나가 잘못돼도 '전부 실패'로만 보여
    어느 키가 문제인지 알 수 없었기 때문이다.

    반환값은 '이 키를 쓸 것인가'다. 인증 실패처럼 확실한 경우만 False이고,
    타임아웃·네트워크 오류는 판단 불가로 보고 True를 준다 — 점검 실패로
    멀쩡한 키를 버리는 것이 훨씬 손해다. 덤으로 이 호출이 모델 예열도 해준다.
    """
    if not api_key:
        KEY_STATUS[label] = "미설정"
        return False

    try:
        resp = requests.post(
            NVIDIA_API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": NVIDIA_MODEL,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 8, "temperature": 0, "stream": False,
                "chat_template_kwargs": {"enable_thinking": False},
            },
            timeout=PROBE_TIMEOUT,
        )
    except Exception as e:
        # 판단 불가 — 키를 버리지 않고 그대로 쓴다. 다만 모델 대기열이 막혔다는 신호라
        # 차단기에 알린다: 점검 8건이 전부 이렇게 끝나면 본 요약은 처음부터 다음 모델로
        # 가서, 막힌 대기열에 16건이 줄을 서 240초씩 버리지 않는다(10분 뒤 시험 호출로 복귀).
        KEY_STATUS[label] = f"확인 불가({type(e).__name__}) — 그대로 사용"
        _health.failure(NVIDIA_MODEL, f"키 점검 {type(e).__name__}")
        return True

    if resp.ok:
        KEY_STATUS[label] = "정상"
        _health.success(NVIDIA_MODEL)
        return True
    if resp.status_code in _FATAL_KEY_STATUSES:
        KEY_STATUS[label] = f"사용 불가 HTTP {resp.status_code}: {resp.text[:100]}"
        return False
    # 429(rate limit)/5xx는 키 자체 문제가 아니다
    KEY_STATUS[label] = f"HTTP {resp.status_code} (키는 유효, 재시도 대상)"
    return True


def key_status_report() -> str:
    if not KEY_STATUS:
        return "(키 점검 기록 없음)"
    width = max(len(k) for k in KEY_STATUS)
    return "\n".join(f"{k.ljust(width)}  {v}" for k, v in sorted(KEY_STATUS.items()))


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

    # 여기까지 왔다는 건 클라우드가 응답은 줬는데 JSON이 아니었다는 뜻이다.
    # call_llm()의 자동 폴백은 '전송 실패'에만 걸리므로 이 경우 로컬이 안 불린다 —
    # 명시적으로 한 번 더 맡긴다. 규칙기반으로 떨어뜨리기 전 마지막 시도다.
    logger.warning("Cloud JSON unparseable — handing this chunk to the local model")
    raw3 = call_local_llm(
        system_prompt + "\n\n설명 없이 JSON만 출력하세요.", user_prompt,
        **{k: v for k, v in llm_kwargs.items() if k in ("temperature", "max_tokens")},
    )
    parsed3 = _try_parse(raw3)
    if parsed3 is not None:
        return parsed3
    salvaged3 = _salvage_array(raw3 or "")
    if salvaged3:
        _record("salvaged")
        return salvaged3

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
