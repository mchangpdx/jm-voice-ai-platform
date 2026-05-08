# CRM Wave 1 — Phone-Keyed Returning Customer Design

**Date**: 2026-05-08
**Branch**: `feature/openai-realtime-migration`
**Author**: Claude (brainstorming session with mchang@jmtechone.com)
**Status**: Approved (pending implementation plan)

---

## 1. Overview

신규 통화에서 발신번호로 `bridge_transactions`를 lookup → 식별된 returning customer 정보를 system prompt 끝(INVARIANTS 직전)에 주입 → 첫 인사부터 personalization 발동. 통화 종료 시 AHT 측정을 영속화하여 효과 검증.

**Goals**:
- Returning caller AHT **-25%** (95s → 72s)
- Name/email auto-fill **100%** (DB hit 시 NATO recital 우회)
- Pilot 효과를 SQL로 명확히 입증 (`crm_returning` 컬럼 기반 before/after 분석)
- 회귀 0건, graceful degrade 보장

**Non-goals (Wave 2 이후 별도 sprint)**:
- "forget me" voice opt-out command
- Tiered opt-in (personalization T2)
- Visit count / LTV / last-visit-date 멘트
- Top-3 favorite items 집계
- No-show flag
- Modifier memory ("oat milk 항상")
- Marketing outreach (win-back, SMS, birthday)
- Admin UI customer search
- Voice biometric, cross-store identity

---

## 2. CRM Feature Taxonomy (Reference)

본 spec은 7개 카테고리 중 **Cat 1, 2 (subset), 3.1, 6.1/6.2, 7.1**에 한정한다. 전체 분류는 brainstorming session 참조.

| Category | Wave 1 포함 | Wave 2+ 후보 |
|---|---|---|
| 1. Identity & Recognition | 1.1 phone lookup, 1.2 returning flag, 1.4 name auto-fill, 1.5 email auto-fill | 1.3 visit count 멘트, 1.6 VIP tier, 1.7 cross-store, 1.8 voice biometric |
| 2. Personalization | 2.1 welcome back, 2.2 "the usual?" | 2.3 top-3, 2.4 last-order recap, 2.5 modifier memory, 2.6 birthday, 2.7 lang pref |
| 3. Order History | 3.1 recent 5 prompt 주입 | 3.2 LTV, 3.3 frequency trend, 3.4 no-show flag, 3.5 avg ticket |
| 4. Marketing & Outreach | — | 4.1–4.5 (TCR/TCPA 별 sprint) |
| 5. Operator/Admin Surface | — | 5.1–5.5 (onboarding sprint와 합류) |
| 6. Privacy & Compliance | 6.1 RLS isolation, 6.2 PII redact | 6.3 voice opt-out, 6.4 retention, 6.5 GDPR |
| 7. Analytics & KPI | 7.1 AHT logging + DB column | 7.2–7.4 (대시보드) |

---

## 3. Architecture

### 3.1 Components (4)

```
[1] services/crm/customer_lookup.py            (신규 ~120 LOC)
    lookup(store_id, phone) → CustomerContext | None
    └─ Supabase REST: bridge_transactions
       filter(store_id, customer_phone, state IN [...])
       order(created_at DESC) limit(5)
       + COUNT (state IN visit-set) for visit_count

[2] services/voice/system_prompt.py            (수정 ~30 LOC)
    build_system_prompt(store, customer_context=None)
    └─ INVARIANTS 직전에 customer_context 블록 삽입
       (None / visit_count==0 → token 0 증분)

[3] api/realtime_voice.py                      (수정 ~25 LOC)
    WebSocket accept 직후:
      ctx = await crm.customer_lookup(store_id, caller_phone)
      instructions = build_system_prompt(store, customer_context=ctx)
    WebSocket close 시:
      background: UPDATE bridge_transactions SET
        call_duration_ms, crm_returning, crm_visit_count,
        crm_usual_offered, crm_usual_accepted
      log: [perf] call_end ...

[4] migration: bridge_transactions에 5개 컬럼 추가
    call_duration_ms, crm_returning, crm_visit_count,
    crm_usual_offered, crm_usual_accepted
```

### 3.2 Layer Placement (CLAUDE.md Section 4)

- `services/crm/` 신설 → **Layer 2 (Universal Shared Skills)** 8번째 스킬
- 모든 vertical(cafe/KBBQ/sushi/...)에서 재사용 가능 — adapter 분기 없음

### 3.3 Wave A.3 패턴 보존

- **Fire-and-forget**: AHT UPDATE는 background task (사용자 통화 종료 차단 X)
- **Graceful degrade**: lookup 실패/timeout → `customer_context=None` first-time path
- **Latency 보호**: `create_order` 흐름 무영향 (lookup은 통화 시작 1회만)
- **로그 패턴**: `[perf] call_end ...` (sync_done/bg_done과 동일 형식)

---

## 4. Data Flow

### 4.1 통화 시작 → 종료 시퀀스

```
[T0] Twilio 통화 인입 → /voice/incoming → WebSocket open
     caller_phone_e164 = "+15035551234"
     store_id = "PDX-cafe-01"

[T1] WebSocket accept (realtime_voice.py)
     ctx = await crm.customer_lookup(store_id, caller_phone_e164)
        ├─ anonymous skip → ctx=None
        ├─ timeout(>500ms) → ctx=None + warn log
        ├─ 5xx → ctx=None + warn log
        └─ ok → CustomerContext(...)
     지연: 80–200ms (Twilio→OpenAI 연결 600–1200ms 안에 흡수)

[T2] build_system_prompt(store, customer_context=ctx)
     ctx is None or ctx.visit_count==0 → 기존 prompt 그대로
     ctx.visit_count >= 1 → INVARIANTS 직전 customer_context 블록 삽입

[T3] OpenAI Realtime session.create + instructions 전송
     첫 인사 즉시 personalized: "Welcome back, Jamie!"

[T4] 통화 진행 (모든 기존 흐름 무영향)
     - menu, modifier, order_lifecycle 그대로
     - "the usual?" LLM 자율 발동 (블록 룰 기반)

[T5] WebSocket close
     duration_ms = T5 - T1
     ctx, tx_id, usual_offered/accepted 캡처
     asyncio.create_task(_persist_call_metrics(...))  # fire-and-forget
     log: [perf] call_end tx=X aht_ms=Y returning=true visits=N
          usual_offered=true usual_accepted=true

[T6] WebSocket fully closed
```

### 4.2 customer_lookup 내부

```python
async def customer_lookup(
    store_id: str,
    caller_phone_e164: str | None,
) -> CustomerContext | None:

    # (1) anonymous skip
    if not caller_phone_e164 or not _is_valid_e164(caller_phone_e164):
        log.info("[crm] anonymous_caller skip_lookup store_id=%s", store_id)
        return None

    # (2) Supabase REST 2개 쿼리 (병렬, 500ms timeout)
    try:
        async with anyio.move_on_after(0.5) as scope:
            recent_task = _fetch_recent_5(store_id, caller_phone_e164)
            count_task  = _fetch_visit_count(store_id, caller_phone_e164)
            recent, count = await asyncio.gather(recent_task, count_task)
        if scope.cancel_called:
            log.warning("[crm] lookup_timeout phone=%s",
                        _redact(caller_phone_e164))
            return None
    except httpx.HTTPError as e:
        # 4xx auth → error, 5xx → warn (Section 6 매트릭스 참조)
        ...
        return None

    # (3) usual_eligible 계산
    usual_eligible = (
        len(recent) >= 2 and _items_match(recent[0], recent[1])
    )

    return CustomerContext(
        visit_count=count,
        recent=recent,
        usual_eligible=usual_eligible,
        name=recent[0].get("customer_name") if recent else None,
        email=recent[0].get("customer_email") if recent else None,
    )
```

### 4.3 거래 이력 필터 분리

- **`recent_transactions` (5건, prompt 주입용)**: state IN `(paid, settled, fired_unpaid)` 만
- **`visit_count`**: state IN `(paid, settled, fired_unpaid, canceled, no_show)` COUNT — returning 판정에만 사용
- 분리 이유: usual 추론에 노이즈 제거 + returning 인식은 빠르게

### 4.4 System Prompt customer_context 블록

```
# Customer Context (returning caller)
- Name: Jamie (use in greeting)
- Visits: 7 | Last: 3 days ago
- Recent orders (paid/settled only):
  1. 2026-05-05  iced oat latte (large) + butter croissant   $9.50
  2. 2026-05-02  iced oat latte (large)                       $6.50
  3. 2026-04-28  iced vanilla latte (medium)                  $6.00
  4. 2026-04-22  iced oat latte (large) + blueberry muffin    $9.25
  5. 2026-04-15  drip coffee (large)                          $4.50

# CRM Rules
- Greet by name once: "Welcome back, Jamie!"
- Email & phone are on file — do NOT ask NATO recital unless customer changes them
- Usual eligible: YES (last 2 orders identical)
  → After greeting, you MAY offer: "Would you like the usual,
    iced oat latte large?"
  → If customer says yes, populate items + modifier from order #1.
  → If customer says no/different, proceed normal menu flow.
- Usual eligible: NO → do NOT use "the usual" phrasing.
```

`visit_count == 0` or `None` → 블록 전체 미주입, token 0.

### 4.5 Returning 판정 + "the usual?" 발동 룰

- `visits == 0`: first-time, 인사 표준
- `visits >= 1`: "Welcome back" 인사 + name/email auto-fill
- `visits >= 2 AND _items_match(recent[0], recent[1])`: "Would you like the usual?" 제안 가능
- 그 외: 일반 메뉴 안내

**`_items_match` 정의 (Wave 1 단순화)**:
- `recent[0].items` 와 `recent[1].items`의 **`item_id` multiset이 정확히 일치**하면 True
- `size` (small/medium/large), `modifier`, `quantity`는 **비교 대상에서 제외** (Wave 1)
- 근거: Pilot에서 단순/안전 기준 우선. modifier-aware 매칭은 modifier 정확도 sprint와 합류 (Wave 2)
- 예: order#0 = `[latte, croissant]`, order#1 = `[croissant, latte]` → True (순서 무관)
- 예: order#0 = `[latte(L)]`, order#1 = `[latte(M)]` → True (size 미고려, Wave 1만)
- "the usual" 발동 시 LLM은 `recent[0]` (가장 최근) items를 정확히 사용 (size/modifier 포함)

---

## 5. Files to Create / Modify

### 5.1 신규 (3)

**`backend/app/services/crm/__init__.py`**
```python
from .customer_lookup import customer_lookup, CustomerContext
__all__ = ["customer_lookup", "CustomerContext"]
```

**`backend/app/services/crm/customer_lookup.py`** (~120 LOC)
- `CustomerContext` dataclass
- `customer_lookup()` async function
- `_items_match()`, `_redact_phone()`, `_redact_email()` helpers
- Constants: `_PAID_STATES`, `_VISIT_STATES`, `_LOOKUP_TIMEOUT_S=0.5`, `_E164_RE`

**`backend/scripts/migrate_bridge_call_metrics.sql`**
```sql
-- Wave 1 CRM: AHT measurement + returning-caller analytics
-- (AHT 측정 + 재방문 분석)
ALTER TABLE bridge_transactions
  ADD COLUMN IF NOT EXISTS call_duration_ms   BIGINT,
  ADD COLUMN IF NOT EXISTS crm_returning      BOOLEAN,
  ADD COLUMN IF NOT EXISTS crm_visit_count    INT,
  ADD COLUMN IF NOT EXISTS crm_usual_offered  BOOLEAN,
  ADD COLUMN IF NOT EXISTS crm_usual_accepted BOOLEAN;

CREATE INDEX IF NOT EXISTS idx_bridge_tx_phone_store
  ON bridge_transactions (store_id, customer_phone, created_at DESC)
  WHERE customer_phone IS NOT NULL;
```

### 5.2 수정 (3)

**`backend/app/services/voice/system_prompt.py`** (~30 LOC 추가)
- `build_system_prompt` 시그니처 확장: `customer_context: CustomerContext | None = None`
- `_render_customer_context_block(ctx)` 함수 추가
- INVARIANTS 직전 블록 삽입
- 하위 호환: 기존 호출자는 default None으로 무영향

**`backend/app/api/realtime_voice.py`** (~25 LOC 추가)
- T1 lookup 추가 (line 574 부근, `build_system_prompt` 직전)
- `session_state["customer_context"]`, `session_state["call_started_at_ms"]` 저장
- T5 close handler에 `_persist_call_metrics(session_state)` background task
- `_detect_usual_in_transcript(session_state)` 휴리스틱 (정규식 `\bthe usual\b`)

**`backend/app/services/bridge/transactions.py`** (~20 LOC 추가)
- 신규 함수 `update_call_metrics(tx_id, call_duration_ms, crm_returning, crm_visit_count, crm_usual_offered, crm_usual_accepted)`
- Supabase REST PATCH `bridge_transactions?id=eq.{tx_id}`
- 실패 시 warn log, raise 안 함 (background 안전)

### 5.3 테스트 (4 신규, 20 cases)

| 파일 | 케이스 |
|---|---|
| `tests/unit/services/crm/test_customer_lookup.py` | 8 (U1–U8) |
| `tests/unit/services/voice/test_system_prompt_customer_block.py` | 5 (P1–P5) |
| `tests/unit/api/test_realtime_voice_call_metrics.py` | 4 (R1–R4) |
| `tests/integration/test_crm_e2e.py` | 3 (I1–I3) |

### 5.4 LOC 합계

| 항목 | LOC |
|---|---|
| 신규 코드 | ~150 |
| 수정 코드 | ~80 |
| 테스트 | ~400 |
| Migration | ~10 |
| **합계** | **~640** |

---

## 6. Error Handling & Graceful Degrade

CRM은 부가 기능이며, 실패 시 통화는 first-time 흐름으로 정상 진행한다.

### 6.1 실패 매트릭스

| # | 시나리오 | 트리거 | 처리 | 사용자 영향 | 로그 |
|---|---|---|---|---|---|
| F1 | Anonymous caller | phone None / Private / 정규식 미일치 | return None | First-time 흐름 | `[crm] anonymous_caller skip_lookup` (info) |
| F2 | Supabase 5xx | DB/네트워크 장애 | catch → None | First-time 흐름 | `[crm] lookup_failed graceful_degrade` (warn) |
| F3 | Timeout (>500ms) | 응답 없음 | `move_on_after` → None | First-time 흐름. 첫 인사 200ms 추가 지연 | `[crm] lookup_timeout` (warn) |
| F4 | 4xx auth/RLS | 키/RLS 오류 | catch → None + **error** | First-time 흐름 | `[crm] lookup_auth_error` (error, alert) |
| F5 | 빈 결과 | 0 rows | `CustomerContext(visit_count=0,...)` | First-time | `[crm] first_time_caller` (info) |
| F6 | items_json malformed | 파싱 오류 | 해당 tx 스킵 | First-time | `[crm] items_json_parse_error` (warn) |
| F7 | prompt build 실패 | 블록 렌더 버그 | catch + ctx=None 재시도 | First-time | `[crm] prompt_build_error fallback_no_ctx` (error) |
| F8 | AHT UPDATE 실패 (T5) | 통화 끝 DB 오류 | catch + warn + raise 안 함 | 0 (이미 통화 끝) | `[perf] call_end_persist_failed` (warn) |
| F9 | tx_id 없음 (mid-call hangup) | 결제 전 종료 | UPDATE 스킵 | 정상 | `[perf] call_end no_tx_skip_update` (info) |
| F10 | OpenAI session.create 실패 | OpenAI 장애 | 기존 fallback 흐름 (Wave 1과 무관) | — | 기존 처리 |

### 6.2 PII Redaction (Cat 6.2 필수)

모든 phone/email 로그는 redact 후 출력:

| 원본 | 로그 출력 |
|---|---|
| `+15035551234` | `+1503***1234` |
| `jamie@example.com` | `j***@example.com` |

`_redact_phone()`, `_redact_email()` — `services/crm/customer_lookup.py` 내 정의, `realtime_voice.py`에서도 import.

### 6.3 RLS 격리 (Cat 6.1)

Supabase REST 호출 시 `store_id`를 query filter에 명시적 포함 (RLS 정책 + filter 이중 방어):

```python
params = {
    "store_id":       f"eq.{store_id}",
    "customer_phone": f"eq.{caller_phone_e164}",
    "state":          f"in.({_PAID_STATES_CSV})",
    "order":          "created_at.desc",
    "limit":          "5",
}
```

테스트 I2: 동일 phone, 다른 store_id 격리 검증.

### 6.4 모니터링 키워드

| 키워드 | 의미 | 대응 |
|---|---|---|
| `[crm] lookup_auth_error` | RLS/키 문제 | 즉시 점검 (PROD_BLOCKER) |
| `[crm] lookup_timeout` | DB 느림 | 빈도 모니터링 |
| `[crm] lookup_failed` | 5xx | 빈도 모니터링 |
| `[crm] first_time_caller` | 신규 통화 | 정상 |
| `[crm] anonymous_caller` | blocked CID | 정상 |
| `[perf] call_end` | 통화 종료 | 정상 (KPI) |
| `[perf] call_end_persist_failed` | AHT 영속화 실패 | 빈도 모니터링 |

---

## 7. Testing Strategy

### 7.1 TDD 작업 순서 (CLAUDE.md Section 3)

각 컴포넌트:
1. 테스트 작성 → fail (Red)
2. 최소 구현 → 통과 (Green)
3. Refactor

### 7.2 Tier 1 — Unit: customer_lookup.py (8 cases)

| # | 시나리오 | 입력 | 기대 |
|---|---|---|---|
| U1 | first-time (0 rows) | phone valid, 빈 응답 | `visit_count=0, recent=[], usual_eligible=False, name=None, email=None` |
| U2 | returning 1건 paid | 1 row | `visit_count=1, recent=[1], usual_eligible=False` |
| U3 | returning 5건 paid, last 2 item_id multiset 동일 | 5 rows | `recent=[5], usual_eligible=True` |
| U4 | returning 7건 — LIMIT 5 | 7 rows | `len(recent)==5` |
| U5 | mix 3 paid + 2 canceled | 5 rows | `visit_count=5, recent=[3]` |
| U6 | anonymous caller | phone=None / "Private" | `None` (lookup 미실행) |
| U7 | Supabase 5xx | mock 5xx | `None` + warn 로그 |
| U8 | Timeout (>500ms) | mock delayed | `None` + warn 로그 |

### 7.3 Tier 2 — Unit: system_prompt.py (5 cases)

| # | 시나리오 | 기대 |
|---|---|---|
| P1 | `customer_context=None` | 블록 미주입 (token 0 증분, 기존 prompt 정확 일치) |
| P2 | `visit_count=0` | 블록 미주입 |
| P3 | `visit_count=1, recent=[1]` | "Welcome back" 블록 + `Usual eligible: NO` |
| P4 | `visit_count=2, last 2 동일` | `Usual eligible: YES` |
| P5 | `visit_count=2, last 2 상이` | `Usual eligible: NO` |

### 7.4 Tier 3 — Unit: realtime_voice.py call metrics (4 cases)

| # | 시나리오 | 기대 |
|---|---|---|
| R1 | call_end with tx_id + ctx | `update_call_metrics` payload: `call_duration_ms, crm_returning=True, crm_visit_count, crm_usual_offered, crm_usual_accepted` |
| R2 | call_end without tx_id (mid-call hangup) | UPDATE 스킵 + `[perf] call_end no_tx_skip_update` 로그 |
| R3 | UPDATE 실패 (DB 5xx) | 통화 종료 정상, warn 로그, raise 0 |
| R4 | `_detect_usual_in_transcript` 정규식 | "the usual" → True; 미포함 → False; 대소문자/구두점 정확 |

### 7.5 Tier 4 — Integration: 실 DB E2E (3 cases)

| # | 시나리오 | 기대 |
|---|---|---|
| I1 | seed 5 paid txs → lookup | recent 5건 정확 정렬(DESC), `visit_count=5` |
| I2 | RLS 격리 | 동일 phone 다른 store_id 격리 검증 |
| I3 | anonymous E2E | phone=null로 모의 통화 → ctx=None, first-time 흐름 정상 |

### 7.6 통과 기준

- **439 + 20 = 459 tests pass** (회귀 0건)
- `pytest backend/tests -k crm` 격리 실행 가능
- Coverage: `services/crm/` ≥ 95%, `system_prompt.py` 신규 블록 100%

### 7.7 Live 검증 (사용자 직접 통화)

| Live | 시나리오 | 검증 |
|---|---|---|
| L1 | 신규 phone 통화 → 주문 → 끊기 | 첫 인사 generic, AHT 측정, `crm_returning=false` |
| L2 | 같은 phone 재통화 (≥2회) | "Welcome back, {name}" 즉시, name/email 안 묻기, `crm_returning=true` |
| L3 | 동일 메뉴 2회 후 3번째 통화 | "Would you like the usual?" 발동, 수락 시 items 자동 채움 |
| L4 | Anonymous (`*67`) 통화 | First-time처럼 정상, `[crm] anonymous_caller` 로그 |

---

## 8. Migration & Rollout

### 8.1 작업 순서 (6 commits)

```
[Commit 1] migration SQL + jm-saas-platform 컬럼명 충돌 검증
[Commit 2] customer_lookup.py + Tier 1 unit tests (8) — TDD
[Commit 3] system_prompt.py customer_context 블록 + Tier 2 (5) — TDD
[Commit 4] realtime_voice.py lookup hook + AHT call_end + Tier 3 (4) — TDD
[Commit 5] integration tests (3) — Tier 4
[Commit 6] docs/crm/wave-1.md + session summary (PDF 아카이빙)
```

각 commit은 `439 + 누적 신규 = pass` 보장.

### 8.2 DB Migration 절차

**Step 1 — jm-saas-platform 전수 조사** (memory `feedback_db_schema_reference.md`):
```sql
SELECT table_name, column_name FROM information_schema.columns
WHERE column_name IN (
  'call_duration_ms','crm_returning','crm_visit_count',
  'crm_usual_offered','crm_usual_accepted'
);
```
충돌 0건 확인 후 → Step 2.

**Step 2 — 마이그레이션 적용**:
```bash
psql "$DB_URL" -f backend/scripts/migrate_bridge_call_metrics.sql
```
- `IF NOT EXISTS` 멱등 (재실행 안전)
- 모든 컬럼 NULLABLE → 기존 행 영향 0
- 인덱스 lookup 성능 보호

**Step 3 — 검증**:
```sql
\d+ bridge_transactions
SELECT COUNT(*) FROM bridge_transactions;  -- migration 전후 동일
EXPLAIN SELECT * FROM bridge_transactions
  WHERE store_id='X' AND customer_phone='+1...'
  ORDER BY created_at DESC LIMIT 5;
-- → Index Scan using idx_bridge_tx_phone_store
```

### 8.3 Rollout Stage

**Stage 1 — Dev (uvicorn local)**:
- 6 commits 순차 적용
- 매 commit `pytest -k crm`
- Live L1–L4 사용자 통화 검증

**Stage 2 — Pilot 매장 (PDX-cafe-01)**:
- migration 적용
- ngrok URL 그대로
- 첫 24시간 모니터링:
  ```bash
  tail -f uvicorn.log | grep -E '\[crm\]|\[perf\] call_end'
  ```
- 24시간 후 SQL 효과 측정:
  ```sql
  SELECT crm_returning,
         AVG(call_duration_ms)/1000.0 AS aht_sec,
         COUNT(*) AS calls
  FROM bridge_transactions
  WHERE store_id='PDX-cafe-01'
    AND created_at >= NOW() - INTERVAL '24 hours'
    AND call_duration_ms IS NOT NULL
  GROUP BY crm_returning;
  ```
- 목표: returning AHT < new AHT × 0.85 (-15% 이상)

**Stage 3 — 추가 매장 확장 (Wave 1 스코프 외)**:
- Pilot 매장 24h 정상 + KPI 검증 후 영업/설치 담당이 추가 매장 onboarding
- main 브랜치 머지는 별도 결정

### 8.4 긴급 롤백

**Code Rollback (환경변수 가드)**:
```bash
CRM_LOOKUP_ENABLED=false uvicorn ...
```
- false → `customer_lookup` 호출 0, `customer_context=None` 항상
- 코드 변경 없이 즉시 first-time 흐름 복귀

**DB Rollback (권장 안 함)**:
- NULLABLE 컬럼이라 두어도 무해 — 기존 흐름 영향 0
- 정말 필요 시 `DROP COLUMN IF EXISTS` (5개)

---

## 9. Success Criteria (Pilot)

| 지표 | Before | Target | 측정 |
|---|---|---|---|
| Returning AHT | ~95s | **≤72s (-25%)** | SQL: `AVG(call_duration_ms) WHERE crm_returning=true` |
| New AHT | ~95s | 변동 없음 (95±5s) | SQL: 동일, `crm_returning=false` |
| Email NATO 시간 | ~22s | ≤2s (returning) | transcript 분석 (수동 샘플링) |
| Name auto-fill 정확도 | 95% | **100%** (DB hit) | live 통화 검증 |
| 회귀 테스트 | 439 | **459 pass** | `pytest backend/tests` |
| Lookup 실패 빈도 | — | <0.5% | `[crm] lookup_failed` 로그 빈도 |

---

## 10. Approved Design Decisions (Q1–Q8 합의)

| Q | 결정 | 근거 |
|---|---|---|
| Q1 | 데이터 윈도우: **최근 5건 raw** | LLM이 패턴 추론, 토큰 무시할 수준 |
| Q2 | Returning ≥1건, "the usual?" ≥2건 + items 동일 | Welcome back은 빠르게, usual은 보수적 |
| Q3 | Lookup 시점: WebSocket accept 직후 await | 첫 인사부터 personalized, +200ms 인지 X |
| Q4 | 거래 필터: `recent` (paid/settled/fired_unpaid) + `visit_count` (전체 5 state) 분리 | usual 노이즈 제거 + returning 빠른 인식 |
| Q5 | Anonymous: lookup 건너뛰기 + first-time 흐름 | 익명성 존중 + 코드 단순 |
| Q6 | Block 배치: INVARIANTS 직전 (B) | recency 보호 (lost-in-middle 회피) |
| Q7 | AHT 측정: log + DB column (C) | 실시간 grep + 영구 SQL 분석 |
| Q8 | 테스트: D안 (20 cases unit + integration) | 회귀 0건 보장 (Wave A.3 패턴) |

## 11. Privacy Path (Path 1 합의)

Pilot 단계 = **implicit only**:
- 통화 중 옵트인 질문 추가하지 않음 (AHT 측정 노이즈 회피)
- 매장 사인보드 + 영수증 푸터 disclosure (영업/설치 담당 제공)
- Wave 2에서 "forget me" voice command + tiered opt-in 도입

근거:
- 결제·영수증·refund용 phone/email은 legitimate business interest (GDPR Art.6(1)(b))
- AHT -25% 깨끗한 측정 보호
- 미국 SMB 음식점 표준 패턴

---

## 12. Out of Scope (Wave 2+ Backlog)

| 기능 | Sprint 후보 |
|---|---|
| "forget me" voice command (Cat 6.3) | Wave 2 |
| Tiered opt-in (T2 personalization) | Wave 2 |
| Visit count / LTV / last-visit 멘트 (Cat 1.3, 3.2) | Wave 2 personalization |
| Top-3 favorite items 집계 (Cat 2.3) | Wave 2 |
| No-show flag (Cat 3.4) | risk customer sprint |
| Modifier memory (Cat 2.5) | modifier 정확도 sprint와 합류 |
| Win-back / SMS / birthday (Cat 4.x) | TCR/TCPA 별 sprint |
| Admin UI customer search (Cat 5.x) | onboarding automation sprint |
| Voice biometric, cross-store identity (Cat 1.7/1.8) | 인프라/보안 검토 별도 |

---

## 13. References

- `CLAUDE.md` — Project Constitution (Section 2 언어, Section 3 TDD, Section 4 Layer)
- `feedback_db_schema_reference.md` — DB 컬럼 추가 전 saas-platform 전수 조사
- `feedback_alert_channel_strategy.md` — 고객 transactional 동의 별도
- `feedback_prompt_length_rule.md` — 시스템 프롬프트 lost-in-middle 회피
- `feedback_careful_change_protocol.md` — 신중 변경, 회귀 방지
- `feedback_loyverse_webhook_unstable.md` — webhook DELETE/POST 금지 (관련 가드)
- `realtime_migration_runbook.md` — 운영 가이드
- `session_resume_2026-05-08_wave-a3.md` — Wave A.3 완료 상태 (latency 10.9× + email 100%)

---

**End of Design Document.**
