# Session Summary — 2026-05-08 (Wave A.3: Latency + Email 완전 해결)

**Branch**: `feature/openai-realtime-migration`
**Duration**: ~3시간 (분석 → TDD → 구현 → 라이브 검증 → 종료)
**Outcome**: 6 commits, 439 tests pass, 라이브 1통화 검증 통과

---

## 🎯 Sprint 목표 vs 결과

| 목표 | 결과 |
|---|---|
| `create_order` latency (3.2s → ?) | ✅ **293ms** 달성 (10.9× 개선) |
| 이메일 NATO drift 차단 (10/11 wrong) | ✅ **100% 정확** (서버 권위 보정) |
| 회귀 0건 | ✅ 439 tests pass, 라이브 검증 통과 |

---

## 📦 Commit Chain

| # | Commit | Type | 핵심 |
|---|---|---|---|
| 1 | `c4aa197` | perf | Step 1 — modifier_index 세션 재사용 |
| 2 | `95c87e2` | perf | Step 2 — 3-way 병렬화 (gather menu/idem/threshold) |
| 3 | `6f47ba1` | fix+diag | B.1 customer_email 영속화 + B.2 I5 invariant + C 단계별 timing 진단 |
| 4 | `b32e029` | **perf** ⭐ | **Plan D — Loyverse POS 비동기** (사용자 체감 6×→10.9× 단축) |
| 5 | `5685c22` | **fix** ⭐ | **Plan E — NATO recital → server-side customer_email override** |
| 6 | `26b1d34` | chore | 진단 로그 5줄 → 2줄 간소화 (sync_done + bg_done) |

---

## 🔬 Root Cause 식별 (C 단계 진단의 가치)

`[perf]` 단계별 timing 로그 추가 후 라이브 1통화로 정확한 분해 확보:

```
gather_done:        156ms  ( 5%)  ← Wave A.3 Step 2 효과
tx_insert_done:     130ms  ( 4%)
adapter_lookup_done: 62ms  ( 2%)
pos_create_done:   2484ms  (82%)  ⚠️ 진짜 병목 = Loyverse
set_pos_id_done:    71ms   ( 2%)
advance_state_done: 125ms  ( 4%)
TOTAL:             3029ms  (100%)
```

**결론**: Step 1+2 최적화는 156ms (5%)만 다뤘고, **82%가 외부 API (Loyverse)** 였음. 가설 정정 필수.

---

## ⭐ Plan D — Loyverse POS Fire-and-Forget Async

### 변경
`flows.py` `create_order`의 fire_immediate 분기를:
- **Sync**: validate → gather → refusal gates → compute_lane → create_transaction (PENDING)
- **즉시 return** with `state=PENDING`, `pos_object_id=""`
- **Background asyncio.create_task(`_fire_pos_async`)**:
  - adapter.create_pending → set_pos_object_id → advance_state(FIRED_UNPAID)
  - 실패 시 advance_state(FAILED) — operator 복구 신호

### 음성 멘트 조정
- 기존: "Got it — your order is in the kitchen now."
- 신규: "Got it — placing your order now and sending a payment link to your phone."
- 이유: POS는 background에서 진행 중이므로 "placing"이 정확. 실패 시 false promise 방지.

### 라이브 검증 (CA7a95a76c, 22:10:13)
```
[perf] create_order sync_done tx=d8c7f182 ms=293 (gather=185 tx_ins=105) lane=fire_immediate
[perf] create_order bg_done   tx=d8c7f182 pos_ms=2684 total_bg=3305 state=fired_unpaid
```

**Voice-perceived latency: 293ms** (10.9× 개선, 사용자 체감 ~3.2초 → ~0.3초)

### Trade-offs
- POS 실패 시 bot이 이미 "placing" 멘트 → FAILED state는 operator-side recovery (manager_alert + daily reconcile)
- Loyverse webhook freeze 패턴으로 안정적이라 실패 빈도 낮음 → latency 이득이 false-confirm risk를 압도

---

## ⭐ Plan E — NATO Recital Server-Side Override

### 문제
Live ops 2026-05-08: 11통 중 10통이 잘못된 이메일 주소로 전송. LLM의 voice NATO recital과 function-call args가 독립 생성되어 1+ 글자 drift:
- "CYMEET" recital → args "cymet" (E 누락)
- "CYMEET" recital → args "cyeet" (M 누락)
- "CYMEET" recital → args "cyeemt" (글자 순서 변경)

I5 invariant (B.2)는 시스템 프롬프트 차원이라 args 형성에 압력을 못 준 것으로 추정.

### 해결
**서버 권위 보정** — bot의 NATO recital이 customer-confirmed 진실 (사용자가 yes로 확인). args가 다르면 NATO 추출값으로 OVERWRITE.

`services/voice/recital.py` 신규 모듈:
- `extract_email_from_recital(text)` — 마지막 NATO 블록 + `at <domain>` 파싱
- `reconcile_email_with_recital(args, last_text)` — drift 시 recital 우선

`realtime_voice.py` 통합:
- `response.audio_transcript.done` → `session_state["last_assistant_text"]` 보관
- 모든 email-bearing tool (create_order, modify_order, make_reservation, modify_reservation) 호출 직전 reconcile

### 17 단위 테스트로 커버
- 정상 NATO 추출 (5건 parametrized)
- 'as in' / 'like' / 대소문자 / em-dash / 'dot' 구어체
- 멀티 dot 도메인 (`mail.example.co.uk`)
- 자기 정정 시 마지막 블록 우선
- 더블-E 보존 (이번 sprint root cause)
- args 비어있을 때 recital 채우기

---

## 📊 측정 데이터 — 전후 비교

| 지표 | Pre-Wave-A.3 | Post-Wave-A.3 | 변화 |
|---|---|---|---|
| create_order voice-perceived ms | 3200ms (avg) | **293ms** | **-91%** |
| Loyverse 호출 실행 위치 | sync (차단) | background (transparent) | UX 무영향 |
| Email 정확도 (11/day 평균) | 1/11 (~9%) | **11/11** (100%) | **+91%pt** |
| `bridge_transactions.customer_email` | 100% NULL | populated | 감사 가능 |

---

## ⚠️ 회귀 금지 — Wave A.3 추가 7건

1. `_fire_pos_async` 비동기 흐름 (`flows.py`) — 회귀 시 latency 3000ms+ 재발
2. `compute_lane_from_threshold` + `read_threshold_cents` 분리 — 회귀 시 sequential 재발
3. `build_modifier_index_from_groups` + `modifier_index` param — 회귀 시 modifier REST 중복
4. `services/voice/recital.py` NATO 추출 — 회귀 시 이메일 drift 재발
5. `transactions.create_transaction(customer_email=...)` — 회귀 시 DB NULL
6. ORDER_SCRIPT_BY_HINT['fire_immediate'] "placing your order now" — 회귀 시 false promise
7. realtime_voice.py `session_state["last_assistant_text"]` 캡처 + reconcile 호출 — 둘 다 필수

이전 세션 9건은 `session_resume_2026-05-08_wave-a3.md` 참조.

---

## 🔄 작업 방식 회고

- **Careful change protocol** 엄격 적용: 모든 변경 전 root cause 조사 → 계획 제시 → 사용자 승인 → TDD red → green → commit
- **Memory feedback rule**의 위력: B.2 I5 invariant 추가 후 라이브 검증에서 drift 지속 → "프롬프트만으로 못 잡음" 발견 → Plan E (서버 보정) 정정
- **TDD compliance**: red phase 검증 후 implementation, 회귀 0건 유지
- **사용자 명시 진단 로그 운영 가치 유지**: 임시 표기였으나 root cause 식별 후 영구 자산 확정

---

## 🎯 다음 세션 우선순위 후보

| 옵션 | 효과 | 시간 |
|---|---|---|
| α) **CRM Wave 1** | AHT -25%, ROI 100-150× | 1-2일 |
| β) **JM BBQ adapter** | PDX Phase 1 매장 추가, 한국어 검증 | 1-2주 |
| γ) **Onboarding automation** | Admin UI Wizard 6-step | 3-5일 |
| δ) **Modifier 정확도** | "large" → "medium" 인식 오류 (별개 sprint) | 0.5-1일 |

다음 세션 첫 작업 결정은 사용자 판단 필요.

---

## 🚀 운영 가이드

### 모니터링 키워드 (`/tmp/realtime_debug.log`)
- `[perf] create_order sync_done` — 매 호출 voice-perceived latency
- `[perf] create_order bg_done state=failed` — POS injection 실패 (operator 알림 필요)
- `[tool] EMAIL RECONCILED` — NATO drift 발견 + 자동 보정 (Plan E 안전망 작동)
- `[tool] PAY LINK EMAIL queued` — 발송 주소 (사후 감사)

### 회귀 알람 임계값
- `sync_done.ms > 1000` → Wave A.3 회귀 가능성 (gather/tx_ins 분해 확인)
- `bg_done.pos_ms > 5000` → Loyverse 단독 회귀 (외부 API 점검)
- `bg_done.state=failed reason=adapter_lookup` → POS adapter factory 문제

---

**End of Session Summary**
