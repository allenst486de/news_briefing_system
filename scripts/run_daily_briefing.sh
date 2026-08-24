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
