# Handoff — 2026-05-18 EOD (eve)

Two parallel tracks active. Each is independently committable.

---

## Track 1 — Backend (Beauty MVP + voice fixes)

1. **오늘 한 일**: Phase 5 라이브 활성화 (Beauty MVP) + vertical-aware prompt 30K→8K 압축 (C1); dispatcher vertical 가드 (C2) + price fallback (C4) + CustomerContext hotfix; modifier `applies_to` 필터 (N1). Commits: `ea84735` → `21f52e1` (9 atomic), 473/473 unit tests pass.
2. **다음 세션에서 가장 먼저 할 일**: `session_resume_2026-05-18_post-fix.md` 읽고 N5 (cancel 메시지) / N2 (cancel 모호) / critical-gaps 4건 중 선택.
3. **절대 하지 말 것**: ORDER vertical SHA256 baseline (cafe/pizza/mexican/kbbq) 깨기; `voice_websocket.py` ORDER prompt 부분 건드리기 (line 301-911 진입점 분기만 추가됨); historical 매장의 `applies_to_categories` 키 변경; 라이브 통화 중 backend 파일 수정.
4. **참고**: `session_resume_2026-05-18_post-fix.md`, `critical_gaps_remaining_2026-05-18.md`, `docs/sessions/2026-05-18_beauty-live-calls/REPORT.md`, `docs/sessions/2026-05-18_beauty-live-calls/VERIFICATION_SCRIPT_V2.md`.

---

## Track 2 — Frontend (Polish day — 13 commits)

1. **오늘 한 일** (eve 세션): **회귀 fix 1** (Store Overview KPI fetch loop — `2becdac` Section Registry refactor 회귀, `handleMetrics`를 `useCallback`으로 안정화) + **Cat E2 token migration** (31 CSS modules, 1,107 hex → token, 11 신규 token) + **Cat C admin polish** (Stores 멀티셀렉트 + bulk Enable/Disable/Delete, Admin Overview donut + call volume bar) + **Cat D2 store polish** (Settings weekly heatmap 7×24, AiVoiceBot inline LCS line diff) + **Cat F1** (AuditLog JSON before/after key-level diff + RAW fallback) + **P0 cleanup** (`recharts ^3.8.1` package.json pin — 이전엔 `--no-save`로 살아남았던 ghost dep, `#7f1d1d` → `--color-danger-deeper`) + **Skeleton sweep 전체** (admin 5 + store 6 + agency 2 페이지, 공통 `<Skeleton>` + `<SkeletonRow>` primitive) + **LoadMore primitive** + Users/Agencies/Stores client-side pagination (50 row chunks) + **AuditLog 모바일 diff break fix** (1-col stack + `overflow-wrap: anywhere`). Commits: `79b1ecd` → `f6297a3` (13 atomic), 모두 push, tsc/build clean throughout.
2. **다음 세션에서 가장 먼저 할 일**: `[[session-resume-2026-05-18-eve-frontend-polish]]` + `[[next-session-frontend-2026-05-19]]` 읽고 carry-over (ArchProof inline hex polish · Onboarding wizard Skeleton 적용 · 기타) 또는 P2 vertical widget (backend `/api/store/appointments` ship 후) 중 선택.
3. **절대 하지 말 것**: `tokens.css`의 11 신규 token alias 깨기 (`--color-brand-soft`, `--color-warn-soft-border` 등 — 매장 daily-use 페이지 전부에서 참조); ArchProof / Store Overview orchestrator 수정 (Section Registry contract); 31 CSS 모듈에서 token → hex 회귀; recharts SVG `fill` attribute에 CSS var() 사용 시도 (SVG attribute는 var() 해석 안 함, 기존 hex literal 유지). Backend track 파일 (templates/, skills/, realtime_voice.py) 절대 건드리지 말 것.
4. **참고**: `[[session-resume-2026-05-18-eve-frontend-polish]]`, `[[next-session-frontend-2026-05-19]]`, `[[feedback-mobile-responsive-mandatory]]`, `docs/sessions/2026-05-18_eve_frontend-polish/SESSION.{md,pdf}`, `frontend/src/components/Skeleton/`, `frontend/src/components/LoadMore/`, `frontend/src/styles/tokens.css`.

---

## Environment state (carry across both tracks)

- **Branch**: `feature/openai-realtime-migration`
- **HEAD**: `f6297a3` (Frontend agency skeleton). Sequence: `ea84735` … `21f52e1` (backend) interleaved with `79b1ecd` … `f6297a3` (frontend).
- **Vite dev server**: PID 5032 alive (`*:5173`). Kill with `kill 5032` if restart needed.
- **Mac LAN IP**: `192.168.0.135` → `http://192.168.0.135:5173` (changed earlier today from `192.168.219.106` — different location).
- **Backend ngrok**: `https://jmtechone.ngrok.app → :8000` — DO NOT STOP (live Twilio webhook).
- **Untracked / staged in flight**: none on frontend side after `f6297a3` push.
