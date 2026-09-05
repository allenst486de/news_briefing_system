#!/bin/bash
# launchd → 실제 브리핑 스크립트 사이의 얇은 래퍼.
#
# 왜 이 파일이 홈 디렉터리에 있나:
# 저장소는 외장 USB 볼륨(/Volumes/D)에 있는데, launchd 에이전트는 외장 볼륨에
# 접근하지 못한다. plist의 StandardOutPath를 거기로 두면 launchd가 로그 파일조차
# 만들지 못해 스크립트를 시작하기도 전에 EX_CONFIG(78)로 죽는다 — 2026-09-05
# 04:30 예약 실행이 이렇게 조용히 실패했다(runs=1 / exit 78 / 로그 0바이트도 없음).
# 동일한 /bin/echo 작업으로 확인: 로그를 홈에 두면 exit 0, 외장 볼륨에 두면 EX_CONFIG.
#
# 그래서 launchd가 만지는 경로(이 스크립트 + 로그)는 전부 내장 디스크에 두고,
# 외장 볼륨 접근은 이 스크립트가 시작된 뒤에만 일어나게 한다.

REPO="/Volumes/D/AI_Projects/Claude/01_Projects/20260203_news_brefing_system"
TARGET="${REPO}/scripts/run_daily_briefing.sh"

echo "===== $(date) 래퍼 시작 ====="

# 외장 볼륨이 안 붙어 있거나(맥 재부팅 후 등) 접근이 막히면 여기서 걸린다.
# 이 로그는 내장 디스크에 남으므로 원인이 반드시 보인다.
if [ ! -d "$REPO" ]; then
  echo "실패: 저장소 경로에 접근할 수 없음 — $REPO"
  echo "외장 볼륨이 마운트되지 않았거나, launchd에 접근 권한이 없습니다."
  echo "볼륨 상태:"
  ls -d /Volumes/* 2>&1
  exit 1
fi

if [ ! -r "$TARGET" ]; then
  echo "실패: 실행 스크립트를 읽을 수 없음 — $TARGET"
  exit 1
fi

echo "저장소 접근 확인됨. 브리핑 실행을 넘긴다."
/bin/bash "$TARGET"
STATUS=$?
echo "===== $(date) 래퍼 종료 (exit $STATUS) ====="
exit $STATUS
