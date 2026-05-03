#!/usr/bin/env bash
# SessionEnd / Stop hook — summarize the just-finished session into
# ./handoff.md (4-line compressed format). Spawns a headless `claude -p`
# call seeded with the tail of the JSONL transcript.
# (세션 종료 시 transcript 요약 → ./handoff.md 덮어쓰기)
#
# Recursion guard: the headless call inherits CLAUDE_HOOK_HANDOFF=1 so
# its own SessionEnd does NOT re-trigger this script.

set -euo pipefail

[[ -n "${CLAUDE_HOOK_HANDOFF:-}" ]] && exit 0

INPUT="$(cat || true)"
TRANSCRIPT="$(printf '%s' "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null || true)"
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(printf '%s' "$INPUT" | jq -r '.cwd // empty' 2>/dev/null || pwd)}"
PROJECT_DIR="${PROJECT_DIR:-$(pwd)}"

[[ -z "$TRANSCRIPT" || ! -f "$TRANSCRIPT" ]] && exit 0

cd "$PROJECT_DIR"

# Extract the last ~200 user/assistant turns as plain text. Skip tool noise
# but keep enough signal for a faithful summary.
# (마지막 200턴 추출 — tool 노이즈 제외, 핵심 메시지만 유지)
CONTEXT="$(jq -r '
    select(.message.role == "user" or .message.role == "assistant")
    | .message.content
    | if type == "string" then .
      elif type == "array" then
        map(select(.type == "text") | .text) | join("\n")
      else empty end
    | select(. != null and . != "")
' "$TRANSCRIPT" 2>/dev/null | tail -c 60000 || true)"

[[ -z "$CONTEXT" ]] && exit 0

PROMPT='다음 transcript를 읽고 ./handoff.md를 정확히 아래 4줄 형식으로만 작성해서 stdout으로 출력해라. 다른 텍스트(인사말, 마크다운 헤더, 설명, 백틱)는 절대 추가하지 마라. 각 항목은 1줄, 한국어로 간결하게.

1. 오늘 한 일: <세미콜론으로 구분된 3가지 핵심 작업>
2. 다음 세션에서 가장 먼저 할 일: <한 문장>
3. 절대 하지 말 것: <시도했는데 안 된 것 / 지금 건드리면 안 되는 것>
4. 참고: <파일 경로 및 외부 링크 — 쉼표로 구분>

Transcript:
'"$CONTEXT"

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

if CLAUDE_HOOK_HANDOFF=1 claude -p "$PROMPT" \
    --output-format text \
    --model claude-haiku-4-5-20251001 \
    > "$TMP" 2>/dev/null; then
    if [[ -s "$TMP" ]]; then
        mv "$TMP" "$PROJECT_DIR/handoff.md"
    fi
fi

exit 0
