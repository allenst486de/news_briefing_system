#!/bin/bash
# 로컬(맥)에서 매일 뉴스 브리핑을 생성하고 main에 커밋 + gh-pages에 배포한다.
# GitHub Actions의 daily_briefing.yml을 대체 — 30분 하드 타임아웃이 없어
# LLM 호출이 오래 걸려도 끝까지 완주한다.
set -uo pipefail

REPO_DIR="/Volumes/D/AI_Projects/Claude/01_Projects/20260203_news_brefing_system"
WORKTREE_DIR="${REPO_DIR}/.ghpages_worktree"
LOG_FILE="${REPO_DIR}/logs/run_$(date +%Y-%m-%d_%H%M%S).log"

exec >>"$LOG_FILE" 2>&1
echo "===== $(date) 실행 시작 ====="

cd "$REPO_DIR" || exit 1

# 원격 최신 상태로 맞춘다 (indicators.yml이 GitHub 쪽에서 계속 main에 push할 수 있음)
git fetch origin main
git merge --ff-only origin/main || { echo "fast-forward 실패 - 로컬 main이 origin과 갈라짐, 수동 확인 필요"; exit 1; }

source venv/bin/activate

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

# 서버 생존 확인은 lms가 아니라 HTTP로 한다 — 매달릴 일이 없고 훨씬 빠르다.
server_up() { curl -sf --max-time 5 "$MODELS_URL" >/dev/null 2>&1; }

if server_up; then
  echo "로컬 LLM 서버 이미 실행 중"
elif command -v lms >/dev/null 2>&1; then
  echo "로컬 LLM 서버 기동 시도"
  run_bounded 60 lms server start >/dev/null 2>&1 || echo "lms server start 시한 초과/실패 — 계속 진행"
else
  echo "lms CLI 없음 — 로컬 폴백 없이 진행"
fi

if server_up; then
  # 모델을 미리 올려둔다. 안 올려도 첫 요청 때 JIT로 로드되지만 그 호출만 늘어진다.
  if curl -sf --max-time 5 "$MODELS_URL" 2>/dev/null | grep -q "$LOCAL_MODEL"; then
    echo "로컬 폴백 준비됨: $LOCAL_MODEL"
  elif command -v lms >/dev/null 2>&1; then
    echo "로컬 폴백 모델 로드: $LOCAL_MODEL"
    run_bounded 300 lms load "$LOCAL_MODEL" --yes >/dev/null 2>&1 \
      || echo "모델 로드 시한 초과/실패 — JIT 로드에 맡기고 진행"
  fi
else
  echo "로컬 LLM 서버 응답 없음 — 폴백 없이 진행(클라우드 → 규칙기반)"
fi

echo "--- main.py 실행 ---"
python main.py
MAIN_EXIT=$?
if [ $MAIN_EXIT -ne 0 ]; then
  echo "main.py 실패 (exit $MAIN_EXIT) - 커밋/배포 중단"
  exit 1
fi

mkdir -p docs data archive

if [[ -z $(git status --porcelain docs/ data/ archive/) ]]; then
  echo "docs/data/archive 변경 없음 - 커밋 생략"
else
  git add docs/ data/ archive/
  git commit -m "Update daily news briefing - $(date +'%Y-%m-%d')"

  PUSHED=0
  for attempt in 1 2 3; do
    if git push origin main; then
      PUSHED=1
      break
    fi
    echo "push 실패 (시도 $attempt) - origin/main으로 rebase 후 재시도"
    git pull --rebase origin main
  done
  if [ "$PUSHED" -ne 1 ]; then
    echo "main push 최종 실패"
    exit 1
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
  git -C "$WORKTREE_DIR" push origin gh-pages
fi

echo "===== $(date) 실행 종료 ====="
