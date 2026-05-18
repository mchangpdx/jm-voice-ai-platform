# Handoff — 2026-05-18 EOD

Two parallel tracks are active. Each track is independently committable; coordination only required for shared schemas (which we don't have right now).

---

## Track 1 — Beauty MVP (Backend, separate worker)

1. **오늘 한 일** (evening batch — Phase 5 live activation + C1-N1 fix sprint, **8 atomic commits**):
   - **Phase 5 라이브 활성화**: JM Beauty Salon (`34f44792...`) phone=+1-971-606-8979 + is_active=True + Twilio webhook auto-provision + menu_items seed (18 services + 33 modifier wires).
   - **C1** `_build_service_prompt` 신규 — vertical-aware 진입점 분기, Beauty prompt 30K→8K (-74%), 식당 용어 전부 제거. ORDER 4 vertical (cafe/pizza/mexican/kbbq) SHA256 byte-for-byte identity 검증.
   - **C2** dispatcher vertical 가드 — cross-vertical tool 호출 차단 (`recent_orders` 등). defense-in-depth.
   - **C4** `insert_appointment` price/duration fallback via service_lookup (Korean booking $0 회귀 차단).
   - **C6** emergency keywords prompt inject — severe reaction turn 1 즉시 transfer_to_manager.
   - **Hotfix** CustomerContext dataclass dot 접근 (WS 2-3s 끊김 차단).
   - **N1** modifier wire `applies_to` / `applies_to_categories` 키 fallback + Beauty yaml 정합 (Manicure에 hair_length 안 물음).
   - **#19** db_seeder vertical_kind 자동 set + service_kind/duration_min 컬럼 propagation.
   - **10 라이브 통화 검증**: 최종 5/5 PASS, Korean Manicure 48% 단축, severe reaction 32s 즉시 transfer.
   - **473 / 473 unit tests pass**.
   - Commits: `21f52e1` / `1dd3af2` / `0f7e459` / `b35868f` / `29a489b` / `6d617dd` / `d020df4` (+ docs 보고서 2건 + verification script v2/v3).

2. **다음 세션에서 가장 먼저 할 일**: `session_resume_2026-05-18_post-fix.md` ⭐⭐ read → 다음 sprint 옵션:
   - **N5 cancel 메시지 강화** (~30분, 추천) — service_type + scheduled_at hint inject
   - **N2 cancel target 모호 처리** (~1h, 정책 결정 필요) — caller 여러 row 시 선택지 제시
   - **N3 args JSON truncation** (~15분) — notes 100자 제한
   - **Critical 4건 sprint** ([[critical_gaps_remaining_2026-05-18]]) — Loyverse inbound webhook / Step6 Test Call / ngrok env var / Twilio 번호 자동 구매

3. **절대 하지 말 것**: 통화 중 backend 파일 수정 (uvicorn reload 통화 끊김); ORDER vertical SHA256 baseline 깨기 (test_service_prompt_builder.py); `_GEMINI_TOOL_DEFS` / `OPENAI_REALTIME_TOOLS` legacy alias 변경; historical cafe/pizza/mexican/kbbq modifier_groups.yaml의 `applies_to_categories` 키 (Beauty만 짧은 `applies_to` 사용); voice_websocket.py ORDER prompt 부분 (line 301-911 — 진입점 분기 1줄만 추가됨); frontend 영역 건드리기.

4. **참고**: `session_resume_2026-05-18_post-fix.md` (EOD 스냅샷) / `critical_gaps_remaining_2026-05-18.md` (4 갭) / `docs/sessions/2026-05-18_automation-audit/REPORT.md` (32-item census) / `docs/sessions/2026-05-18_beauty-live-calls/REPORT.md` (분석 보고서) / `docs/sessions/2026-05-18_beauty-live-calls/VERIFICATION_SCRIPT_V2.md` (5 시나리오 turn-by-turn).

5. **라이브 인프라 (이어서)**: uvicorn `--reload` PID 24872, ngrok `https://jmtechone.ngrok.app` → `:8000`. Beauty 번호 `+1-971-606-8979`. 모니터링 `tail -f /tmp/realtime_debug.log | grep -E "kind=|tool|caller:|agent:|BLOCKED"`.

---

## Track 2 — Frontend (Admin/UI, this Claude)

1. **오늘 한 일** (PM 두 세션): **Frontend Foundation Day — 8 atomic commits**. Mobile responsive 31/31 closed (영구 룰 `[[feedback-mobile-responsive-mandatory]]`) + Architecture Proof v2 8-section Registry (HeroKpi count-up + 4-layer SVG + Competitive scorecard + ROI calculator + sticky TOC + README) + Store Overview → Section Registry (vertical-aware via `visibleFor`) + Users 인라인 role select + AuditLog chip filters + range picker + breakpoint 100% standard (640/1024) + CSS design tokens 인프라 (tokens.css + main.tsx import). 38 files / ≈ +2,400 LOC. Commits: 9544475 / 5eee4fd / df42e6f / c92beed / 97ff16e / 2becdac / abd88ab / ce81d36 — 모두 push.
2. **다음 세션에서 가장 먼저 할 일**: `[[next-session-frontend-2026-05-19]]` memory read → 옵션 4개 중 사용자에게 선택받기 (Cat E2 토큰 sweep / Cat C admin polish 나머지 / Cat D2 store polish / P2 vertical widgets — backend 의존). 권장 1순위: Cat E2 (다음 모든 UI 작업이 빨라짐).
3. **절대 하지 말 것**: ArchProof 또는 Store Overview의 orchestrator 수정 (Section Registry 패턴 contract); 이번 세션에서 만진 31 CSS 파일을 다시 비표준 breakpoint로 회귀; backend track 파일 건드리기 (templates/, skills/appointment/, realtime_voice.py); 백엔드 ngrok tunnel jmtechone.ngrok.app 끄기.
4. **참고**: `[[session-resume-2026-05-18-responsive]]`, `[[next-session-frontend-2026-05-19]]`, `[[feedback-mobile-responsive-mandatory]]` (31/31 마크), docs/sessions/2026-05-18_responsive-and-proof-v2/SESSION.pdf (435KB), frontend/src/styles/tokens.css, frontend/src/views/admin/proof/README.md.

---

## Environment state (carry across both tracks)

- **Branch**: `feature/openai-realtime-migration`
- **HEAD**: `ce81d36` (Frontend Cat E tokens). Backend worker may push more by next session start.
- **Vite dev server**: PID 5032 alive (`*:5173`). Kill with `kill 5032` if needed.
- **Mac LAN IP**: `192.168.219.106` → `http://192.168.219.106:5173`
- **Backend ngrok**: `https://jmtechone.ngrok.app → :8000` — DO NOT STOP (live Twilio webhook).
- **Untracked / staged in flight**: none on frontend side. Backend worker manages own state.

---

## Frontend backlog snapshot (after 2026-05-18 PM)

| Cat | Status | Notes |
|---|---|---|
| A. Mobile responsive 11 + breakpoint normalization | ✅ DONE | 31/31 modules, 0 non-standard widths |
| B. ArchProof v2 — Registry + 8 sections + README + desktop polish | ✅ DONE | — |
| C. Admin polish | 🟡 partial | Users + AuditLog ✅; Stores bulk + System Health polling + Overview charts pending |
| D1. Store Overview Section Registry | ✅ DONE | vertical-aware via visibleFor |
| D2. Analytics + Settings + AI Voice Bot polish | ⏳ pending | Cat D2 in next session |
| E1. Design tokens scaffold | ✅ DONE | tokens.css + main.tsx import |
| E2. Token migration sweep across 31 modules | ⏳ pending | Highest leverage next move |
| P1.1. 768 breakpoint normalization | ✅ DONE | 13 files → 3 to 640, 10 to 1024 |
| P2. Vertical widgets (AppointmentsSection etc.) | ⏳ blocked | Awaits Beauty MVP backend `/api/store/appointments` |
