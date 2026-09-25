#!/bin/bash
# 로컬(맥)에서 매일 뉴스 브리핑을 생성하고 main에 커밋 + gh-pages에 배포한다.
# GitHub Actions의 daily_briefing.yml을 대체 — 30분 하드 타임아웃이 없어
# LLM 호출이 오래 걸려도 끝까지 완주한다.
#
# launchd가 하루 여러 번 부른다(03:30 본 실행 + 05:45·07:30 재확인 + 로그인 직후).
# 오늘 텔레그램까지 보냈으면 곧바로 끝나고, 안 보냈으면(맥이 꺼져 있었거나 앞 실행이
# 실패) 그때 만든다. 같은 날 두 번 보내지 않는 기준은 main.py가 전송 직후 남기는
# 완료 표시 파일이다.
set -uo pipefail

REPO_DIR="/Volumes/D/AI_Projects/Claude/01_Projects/20260203_news_brefing_system"
WORKTREE_DIR="${REPO_DIR}/.ghpages_worktree"
TODAY="$(date +%Y-%m-%d)"

# 상태 파일은 내장 디스크에 둔다 — 외장 볼륨 문제와 상관없이 남아야 한다
STATE_DIR="$HOME/Library/Application Support/news-briefing"
SENT_MARKER="${STATE_DIR}/sent-${TODAY}"
LOCK_DIR="${STATE_DIR}/run.lock"
mkdir -p "$STATE_DIR"

# 낱말퍼즐 앱용 용어 채우기 — 브리핑과 별개로 항상 확인한다(아래 fill_app_terms).
# 이미 보낸 날에도 이 확인은 한다: 앱은 08:00에 오늘 용어를 여는데 GitHub 예약 실행은
# 1~2시간 늦게 돌아 07:40 마감을 넘기는 날이 많았다(9/15~9/22 중 6일 비어 있었다).
# 맥은 03:30·05:45·07:30에 확실히 도므로 여기서 먼저 채운다. 목표 개수가 이미 있으면
# app_terms.py가 NVIDIA를 부르지 않고 바로 끝난다.
if [ -f "$SENT_MARKER" ]; then
  echo "$(date '+%F %T') 오늘 브리핑은 이미 전송됨 — 브리핑은 건너뜀, 앱용 용어만 확인"
  SKIP_BRIEFING=1
else
  SKIP_BRIEFING=0
fi

# 만회 실행 허용 시간: 03:25~17:59. 새벽 3시 전 재부팅으로 불린 경우는 03:30 본 실행에
# 맡기고, 저녁 이후에는 그날 브리핑을 새로 보내지 않는다(다음 날 아침 것과 겹친다).
NOW_HM=$((10#$(date +%H%M)))
if [ "$NOW_HM" -lt 325 ] || [ "$NOW_HM" -ge 1800 ]; then
  echo "$(date '+%F %T') 실행 시간대 밖(${NOW_HM}) — 건너뜀"
  exit 0
fi

# 동시에 두 개가 돌면 텔레그램이 두 번 나가고 git이 엉킨다. mkdir은 원자적이라 잠금으로 쓴다.
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  OTHER_PID="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  if [ -n "$OTHER_PID" ] && kill -0 "$OTHER_PID" 2>/dev/null; then
    echo "$(date '+%F %T') 다른 실행(pid $OTHER_PID)이 진행 중 — 건너뜀"
    exit 0
  fi
  echo "$(date '+%F %T') 주인 없는 잠금을 치우고 진행"
  rm -rf "$LOCK_DIR"
  mkdir "$LOCK_DIR" || exit 1
fi
echo $$ > "$LOCK_DIR/pid"
trap 'rm -rf "$LOCK_DIR"' EXIT

LOG_FILE="${REPO_DIR}/logs/run_$(date +%Y-%m-%d_%H%M%S).log"
exec >>"$LOG_FILE" 2>&1
echo "===== $(date) 실행 시작 ====="

cd "$REPO_DIR" || exit 1

# macOS에는 GNU timeout이 없다 — 백그라운드로 띄우고 시한이 지나면 죽인다.
run_bounded() {
  local secs="$1"; shift
  "$@" &
  local pid=$! waited=0
  while kill -0 "$pid" 2>/dev/null; do
    if [ "$waited" -ge "$secs" ]; then
      kill -9 "$pid" 2>/dev/null
      wait "$pid" 2>/dev/null
      return 124
    fi
    sleep 1
    waited=$((waited + 1))
  done
  wait "$pid"
}

# 원격 최신 상태로 맞춘다 (indicators.yml·app_terms.yml이 GitHub 쪽에서 main에 push한다).
# 예전에는 fast-forward가 안 되면 그 자리에서 끝났다 — 그날 브리핑이 통째로 안 나갔다.
# 브리핑 전송이 먼저다: rebase로 맞춰 보고, 그래도 안 되면 로컬 상태로 만들고 보낸다
# (커밋·push는 아래에서 다시 rebase를 시도한다).
run_bounded 120 git fetch origin main || echo "git fetch 실패/시한 초과 — 로컬 상태로 진행"
if ! git merge --ff-only origin/main; then
  echo "fast-forward 불가 — origin/main 위로 rebase 시도"
  if ! git rebase origin/main; then
    git rebase --abort 2>/dev/null
    echo "rebase 실패 — 로컬 상태 그대로 브리핑을 만든다(push는 뒤에서 재시도)"
  fi
fi

source venv/bin/activate

# --- 낱말퍼즐 앱용 용어 ---
# 채운 뒤 data/app_terms만 따로 커밋해 main에 올린다(앱이 여기서 읽어 간다).
# 날짜 없이 부르면 07:40 마감이 적용되고, 마감이 지난 뒤(재부팅 후 만회 등)에는
# 오늘 날짜를 지정해 마감 없이 채운다 — 늦어도 안 채우는 것보다 낫다.
# GitHub 쪽 예약 실행도 같은 파일을 만질 수 있어 push가 겹치면 내 커밋만 버리고
# origin 것을 따른다(다음 확인 때 빈 곳이 있으면 다시 채운다). 브리핑 커밋은 건드리지 않는다.
# 오늘 앱용 파일에 든 용어 수(파일이 없거나 깨졌으면 0)
app_terms_count() {
  python - "$(date +%Y-%m-%d)" <<'PY'
import json, sys
day = sys.argv[1]
try:
    with open(f"data/app_terms/{day[:4]}/{day[5:]}.json", encoding="utf-8") as f:
        print(len(json.load(f).get("terms", [])))
except Exception:
    print(0)
PY
}

# 앱은 하루 5개를 싣고, 남는 것은 LLM이 실패한 날 앱이 끌어 쓰는 비축분이다(퍼즐 저장소
# .github/affairs/publish.py가 지난 이틀치의 남은 용어로 채운다). 그래서 재확인 실행
# (05:45·07:30·로그인 후)도 하루 목표 10개까지 채운다. 브리핑이 끝난 뒤라 NVIDIA 시간을
# 더 써도 브리핑에는 영향이 없다. 10개가 이미 있으면 NVIDIA를 부르지 않고 건너뛴다.
APP_TARGET_TERMS=10

fill_app_terms() {
  echo "--- 앱용 시사용어 ---"
  if [ "${1:-}" = "recheck" ]; then
    local have
    have="$(app_terms_count)"
    if [ "$have" -ge "$APP_TARGET_TERMS" ]; then
      echo "오늘 앱용 용어 ${have}개 — 목표(${APP_TARGET_TERMS}개)를 채웠으므로 건너뜀"
      return 0
    fi
    echo "오늘 앱용 용어 ${have}개 — 목표 ${APP_TARGET_TERMS}개까지 채움(5개 넘는 몫은 비축분)"
  fi
  local args=()
  if [ "$((10#$(date +%H%M)))" -ge 740 ]; then
    args=(--date "$(date +%Y-%m-%d)")
  fi
  run_bounded 1800 python app_terms.py ${args[@]+"${args[@]}"} || echo "app_terms.py 실패/시한 초과 — 다음 확인 때 이어서"

  if [[ -z $(git status --porcelain data/app_terms/) ]]; then
    echo "앱용 용어 변경 없음"
    return 0
  fi
  git add data/app_terms/
  git commit -q -m "chore: fill app terms $(date +%Y-%m-%d)"
  for attempt in 1 2 3; do
    if run_bounded 120 git push origin main; then
      echo "앱용 용어 push 완료"
      return 0
    fi
    run_bounded 120 git pull --rebase origin main && continue
    git rebase --abort 2>/dev/null
    break
  done
  echo "앱용 용어 push 실패 — 방금 만든 커밋을 버리고 origin을 따른다(다음 확인 때 다시 채움)"
  # --hard 는 저장소의 다른 파일에 있던 저장 안 한 수정까지 지운다 — 방금 커밋 하나만 되돌린다
  git reset -q --keep HEAD~1 || echo "커밋 되돌리기 실패 — 로컬에 남겨 두고 다음 실행 때 다시 push"
  return 1
}

if [ "$SKIP_BRIEFING" -eq 1 ]; then
  fill_app_terms recheck
  echo "===== $(date) 실행 종료 (앱용 용어 확인만) ====="
  exit 0
fi

# --- 로컬 LLM 폴백 준비 ---
# 클라우드가 실패한 청크를 받아낼 안전망. 여기서 못 띄워도 파이프라인은 그대로
# 진행한다(클라우드 → 규칙기반). 안전망이 없는 것뿐이지 장애는 아니다.
#
# ⚠️ lms 명령은 반드시 시한을 걸어 부른다. launchd 환경(TTY 없음)에서
# `lms server start`가 서버가 이미 떠 있는데도 반환하지 않고 무한 대기했다 —
# 브리핑 전체가 그 자리에서 멈췄다(2026-09-05 09:43 실행, 수동 kill로 확인).
# 안전망을 준비하다가 본 파이프라인을 죽이는 건 앞뒤가 바뀐 것이다.
export PATH="$PATH:$HOME/.lmstudio/bin"
LOCAL_MODEL="${LOCAL_LLM_MODEL:-google/gemma-4-31b-qat}"
LOCAL_URL="${LOCAL_LLM_URL:-http://localhost:1234/v1/chat/completions}"
MODELS_URL="${LOCAL_URL%/chat/completions}/models"
# LM Studio 전용 목록 — 모델마다 state(loaded/not-loaded)를 준다
STATE_URL="${LOCAL_URL%/v1/chat/completions}/api/v0/models"

# 서버 생존 확인은 lms가 아니라 HTTP로 한다 — 매달릴 일이 없고 훨씬 빠르다.
server_up() { curl -sf --max-time 5 "$MODELS_URL" >/dev/null 2>&1; }

# /v1/models는 '받아 둔' 모델을 전부 나열한다 — 예전에는 여기서 이름만 찾고 '올라가 있다'로
# 착각해 로드를 건너뛰었고, 첫 요청이 JIT 로드를 떠안아 타임아웃 났다(9/18).
model_loaded() {
  curl -sf --max-time 5 "$STATE_URL" 2>/dev/null | python3 -c '
import json, sys
want = sys.argv[1]
try:
    data = json.load(sys.stdin).get("data", [])
except Exception:
    sys.exit(1)
sys.exit(0 if any(m.get("id") == want and m.get("state") == "loaded" for m in data) else 1)
' "$LOCAL_MODEL"
}

if server_up; then
  echo "로컬 LLM 서버 이미 실행 중"
elif command -v lms >/dev/null 2>&1; then
  echo "로컬 LLM 서버 기동 시도"
  run_bounded 60 lms server start >/dev/null 2>&1 || echo "lms server start 시한 초과/실패 — 계속 진행"
else
  echo "lms CLI 없음 — 로컬 폴백 없이 진행"
fi

if server_up; then
  if model_loaded; then
    echo "로컬 폴백 준비됨(이미 올라가 있음): $LOCAL_MODEL"
  else
    echo "로컬 폴백 모델 로드: $LOCAL_MODEL"
    if command -v lms >/dev/null 2>&1; then
      run_bounded 300 lms load "$LOCAL_MODEL" --yes >/dev/null 2>&1 \
        || echo "lms load 시한 초과/실패 — 예열 요청으로 JIT 로드 시도"
    fi
    # 짧은 요청 하나로 확실히 올려 둔다(JIT 로드 포함). 본 요약 청크가 로드 시간을 떠안지 않게.
    if ! model_loaded; then
      curl -s --max-time 420 "$LOCAL_URL" -H 'Content-Type: application/json' \
        -d "{\"model\":\"$LOCAL_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"ping\"}],\"max_tokens\":4}" \
        >/dev/null 2>&1
    fi
    if model_loaded; then
      echo "로컬 폴백 준비됨: $LOCAL_MODEL"
    else
      echo "로컬 폴백 모델을 올리지 못함 — 클라우드 사다리 → 규칙기반으로 진행"
    fi
  fi
else
  echo "로컬 LLM 서버 응답 없음 — 폴백 없이 진행(클라우드 → 규칙기반)"
fi

echo "--- main.py 실행 ---"
# main.py는 전송이 끝나면 이 파일을 남긴다. 다음 호출(05:45·07:30·로그인)이 보고 건너뛴다.
export BRIEFING_SENT_MARKER="$SENT_MARKER"
# 무엇이 매달리든 3시간이면 끊는다 — 그래야 다음 재확인 실행이 만회할 수 있다.
run_bounded 10800 python main.py
MAIN_EXIT=$?
case $MAIN_EXIT in
  0) ;;
  3) echo "main.py: 사이트는 만들었지만 텔레그램 전송 실패 — 배포는 진행, 다음 재확인 때 다시 보냄" ;;
  124) echo "main.py 3시간 초과로 중단 — 커밋/배포 중단, 다음 재확인 때 다시 시도"; exit 1 ;;
  *) echo "main.py 실패 (exit $MAIN_EXIT) - 커밋/배포 중단, 다음 재확인 때 다시 시도"; exit 1 ;;
esac

mkdir -p docs data archive

if [[ -z $(git status --porcelain docs/ data/ archive/) ]]; then
  echo "docs/data/archive 변경 없음 - 커밋 생략"
else
  git add docs/ data/ archive/
  git commit -m "Update daily news briefing - $(date +'%Y-%m-%d')"

  PUSHED=0
  for attempt in 1 2 3; do
    if run_bounded 120 git push origin main; then
      PUSHED=1
      break
    fi
    echo "push 실패 (시도 $attempt) - origin/main으로 rebase 후 재시도"
    run_bounded 120 git pull --rebase origin main || git rebase --abort 2>/dev/null
    sleep 10
  done
  if [ "$PUSHED" -ne 1 ]; then
    # main push가 안 돼도 사이트 배포(gh-pages)는 따로 된다 — 여기서 끝내지 않는다
    echo "main push 최종 실패 — 커밋은 로컬에 남음(다음 실행 때 같이 올라감). gh-pages 배포는 계속"
  fi
fi

echo "--- gh-pages 배포 ---"
if [ ! -d "$WORKTREE_DIR" ]; then
  git fetch origin gh-pages
  git worktree add "$WORKTREE_DIR" gh-pages
fi

git -C "$WORKTREE_DIR" fetch origin gh-pages
git -C "$WORKTREE_DIR" reset --hard origin/gh-pages

rsync -a --delete --exclude '.git' "${REPO_DIR}/docs/" "${WORKTREE_DIR}/"

if [[ -z $(git -C "$WORKTREE_DIR" status --porcelain) ]]; then
  echo "gh-pages 변경 없음 - 배포 생략"
else
  git -C "$WORKTREE_DIR" add -A
  git -C "$WORKTREE_DIR" commit -m "Deploy docs - $(date +'%Y-%m-%d')"
  DEPLOYED=0
  for attempt in 1 2 3; do
    if run_bounded 120 git -C "$WORKTREE_DIR" push origin gh-pages; then
      DEPLOYED=1
      break
    fi
    echo "gh-pages push 실패 (시도 $attempt) — 30초 뒤 재시도"
    sleep 30
  done
  [ "$DEPLOYED" -eq 1 ] || echo "gh-pages 배포 최종 실패 — 다음 실행 때 같이 올라감"
fi

# 브리핑이 방금 오늘 시사용어(data/terms)를 쌓았으니 앱용은 그 이름을 그대로 가져와
# 호출 한 번으로 끝난다. 여기서 실패해도 브리핑은 이미 나갔다.
fill_app_terms || true

echo "===== $(date) 실행 종료 (main exit $MAIN_EXIT) ====="
