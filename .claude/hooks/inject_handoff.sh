#!/usr/bin/env bash
# SessionStart hook — inject ./handoff.md (if present) into the new session's
# context. Stdout from a SessionStart hook is added as additionalContext.
# (세션 시작 시 ./handoff.md 자동 주입)

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
HANDOFF="$PROJECT_DIR/handoff.md"

[[ -f "$HANDOFF" ]] || exit 0

cat <<EOF
## Previous session handoff (auto-injected from ./handoff.md)

$(cat "$HANDOFF")
EOF
