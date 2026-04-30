#!/usr/bin/env bash
# Phase F-1 검증용 — ngrok 터널 상태 + 최근 HTTP 요청 ISO 시각 출력
# (zsh ? 글로빙 회피를 위해 작은따옴표로 URL 감싸기)
#
# 실행:
#   bash scripts/inspect_ngrok.sh

set -u

NGROK_API="http://localhost:4040/api"

echo "=== [1/2] 활성 터널 ==="
if ! curl -fsS "$NGROK_API/tunnels" >/dev/null 2>&1; then
    echo "  ❌ ngrok dashboard($NGROK_API)에 접근 불가."
    echo "     ngrok이 실행 중이 아닙니다. 새 터미널에서:"
    echo "       ngrok http 8000"
    exit 1
fi

curl -fsS "$NGROK_API/tunnels" | python3 -c "
import sys, json
d = json.load(sys.stdin)
tunnels = d.get('tunnels', [])
if not tunnels:
    print('  ❌ 활성 터널 0개')
    sys.exit(1)
for t in tunnels:
    print(f\"  ✓ {t['public_url']}  ->  {t['config']['addr']}\")
"

echo ""
echo "=== [2/2] 최근 HTTP 요청 20건 (ISO 시각) ==="
curl -fsS "$NGROK_API/requests/http?limit=20" | python3 -c "
import sys, json
data = json.load(sys.stdin)
rows = data.get('requests', [])
if not rows:
    print('  (요청 기록 없음 — ngrok 재시작 후 첫 요청 대기 중)')
    sys.exit(0)
for r in rows:
    start  = r.get('start', '?')
    method = r['request']['method']
    uri    = r['request']['uri']
    code   = r['response'].get('status_code', '?')
    print(f\"  {start}  {method:5}  {code}  {uri}\")
"
