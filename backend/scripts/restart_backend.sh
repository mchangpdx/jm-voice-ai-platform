#!/usr/bin/env bash
# Phase F-1 검증용 — backend를 깨끗하게 1개 + 로그 파일과 함께 재기동
# (--reload 끔: 통화 도중 reload로 WebSocket 끊기는 사고 차단)
#
# 실행:
#   cd /Users/mchangpdx/jm-voice-ai-platform/backend
#   bash scripts/restart_backend.sh
#
# 결과는 /tmp/backend.log 에 기록됨. 실시간 모니터:
#   tail -f /tmp/backend.log

set -u
cd "$(dirname "$0")/.."

LOG=/tmp/backend.log

echo "=== [1/4] uvicorn 프로세스 정리 ==="
pkill -f "uvicorn app.main" 2>/dev/null || true
sleep 2

echo "=== [2/4] 8000 포트 점유 확인 ==="
if lsof -i :8000 -sTCP:LISTEN >/dev/null 2>&1; then
    echo "  ⚠️  8000 포트가 여전히 점유됨. 강제 종료:"
    lsof -ti :8000 -sTCP:LISTEN | xargs -r kill -9
    sleep 1
fi
lsof -i :8000 -sTCP:LISTEN || echo "  ✓ 8000 포트 비어있음"

echo "=== [3/4] backend 재기동 (--reload 없음, 로그 -> $LOG) ==="
nohup .venv/bin/uvicorn app.main:app \
    --host 127.0.0.1 --port 8000 --log-level info \
    > "$LOG" 2>&1 &
PID=$!
echo "  BACKEND_PID=$PID"
sleep 4

echo "=== [4/4] health 검증 ==="
if curl -fsS -o /dev/null http://localhost:8000/health; then
    echo "  ✓ /health 200 OK"
    echo "  --- 시작 로그 (마지막 20줄) ---"
    tail -20 "$LOG"
else
    echo "  ❌ health 실패 — 로그 확인:"
    tail -50 "$LOG"
    exit 1
fi

echo ""
echo "✅ backend 준비 완료. 다음:"
echo "   1) 다른 터미널에서:  tail -f $LOG"
echo "   2) 시나리오 1 통화 진행"
echo "   3) 끝나면:  bash scripts/inspect_ngrok.sh"
echo "   4) Supabase에서:  scripts/verify_scenario1.sql 실행"
