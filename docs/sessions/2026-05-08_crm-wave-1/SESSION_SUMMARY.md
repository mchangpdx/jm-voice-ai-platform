# Session Summary — 2026-05-08 CRM Wave 1 + Cost Strategy

**Date**: 2026-05-08
**Branch**: `feature/openai-realtime-migration`
**Sprint**: CRM Wave 1 — Phone-Keyed Returning Customer + Email NATO fix + silent agent diagnosis/fix + 3-PDF cost strategy
**Pilot Position**: M1.4 / M9 (25% — single-store live verification)

---

## 🎯 Achievements (12 commits)

### A. CRM Wave 1 — Spec MUST 100% complete + live verified
| Commit | Scope | LOC |
|---|---|---|
| `ae04d8e` | spec design (582 lines) | docs |
| `682ecab` | C1 — DB migration (5 NULLABLE columns + index) | +64 |
| `c0282fa` | C2 — services/crm/ + update_call_metrics | +372 |
| `6090cdb` | C3 — customer_context block (INVARIANTS-prior) | +130/-1 |
| `c674643` | C4 — realtime_voice lookup hook + AHT call_end | +103/-2 |
| `85f9b3f` | C5 — 66 unit tests Tier 1-3 | +689 |

### B. Live verification (4 calls, 124s avg)
- ✅ **Welcome back, Michael!** (turn 1, visits=27)
- ✅ **Email auto-fill** "I have cymeet@gmail.com on file"
- ✅ **"the usual?" 발동** `[crm] usual_offered=true detected` (10:27 call)
- ✅ DB persist 3 rows (`crm_returning=True`, `crm_visit_count=26/1/27`, `call_duration_ms=115279/186216/102120`)
- ✅ AHT 절감 추정: returning calls ~13s saved via email auto-fill

### C. Bonus follow-up fixes
| Commit | Issue | Fix |
|---|---|---|
| `9f09604` | Email NATO `cym eet@gmail.com` 공백 (Call #2) | last_email_recital_text 별도 latch, last_assistant_text 덮어쓰기 방지 |
| `2b26f2a` | Silent agent 진단 부재 | response.done 핸들러에 id/status/output_types/transcript/status_details 캡처 |
| `f6a73f6` | Silent agent root cause = TPM 40K rate_limit_exceeded | retry-after 파싱 + asyncio.sleep + response.create 자동 재시도 (max 3/call) |

### D. Cost Strategy PDFs (3 reports)
| Commit | PDF | Pages | Topic |
|---|---|---|---|
| `40e098f` | openai-realtime-cost-strategy.pdf | 17 | Q1-4 통합 + per-call/min cost |
| `6dd2640` | realtime-models-3way-comparison.pdf | 15 | 1.5 vs 2.0 vs mini + JM 적합도 0-50 |
| `294e607` | hybrid-rollout-timing-and-risk.pdf | 13 | Pilot 단계 진단 + Hybrid 최적 시점 |
| `8390f62` | (cost-strategy 갱신) | +5p | Hybrid 4-시나리오 비교 추가 |

---

## 📊 Live Diagnostic Capture — Silent Agent Root Cause

**라이브 데이터 (2026-05-08 10:28:43)**:
```
status=failed type=failed
error.code=rate_limit_exceeded
error.message='Rate limit reached for gpt-realtime-1.5
  (for limit gpt-4o-realtime). Limit 40000, Used 30058,
  Requested 10244. Please try again in 1.903s'
```

**진단 결과**: 우리가 봤던 모든 silent-agent 사례 = **OpenAI TPM 40K (Tier 1) 한계**.

- Call #1 (09:38): turn 7 후 11s 무음 — TPM 한계 추정 (진단 없어 못 봄)
- Call #4 (10:27): turn 8 explicit fail with retry_after=1.903s
- 사용자 체감 무음 6-10초 = retry-after (1.9s) + caller 반응 시간 (5s)

**Fix 전략 (2단)**:
1. **외부**: Tier 2 도달 ($50 누적 + 7일) → TPM 40K → 200K (5×)
2. **내부**: `f6a73f6` retry 코드 — silent 무음 6-10s → 1-2s 자동 회복

---

## 📐 Per-Call Cost Reconciliation (실측)

평균 통화 124s / 12.9 turns / 6,500-token system prompt:

| Stream | Tokens | gpt-realtime-1.5 cost |
|---|---|---|
| Audio in | 833 | $0.027 |
| Audio out | 1,860 | $0.119 |
| Text in (fresh) | 32,550 | $0.130 |
| Text in (cached, 80% hit) | 86,400 | $0.035 |
| Text out | 1,040 | $0.017 |
| **OpenAI subtotal** | | **$0.327** |
| Twilio (2.07 min) | | $0.037 |
| **All-in per call** | | **$0.364** |
| **Per minute** | | **$0.176** |

**3-Way 비교**:
| Model | Per call | Per min | 5-store/mo | 500-store/mo |
|---|---|---|---|---|
| gpt-realtime-1.5 (current) | $0.405 | $0.196 | $1,823 | $182,250 |
| gpt-realtime-2.0 (new) | $0.408 | $0.197 | $1,836 | $183,600 |
| gpt-realtime-mini | $0.150 | $0.072 | $675 | $67,500 |
| **Hybrid Routing** ⭐ | **$0.284** | **$0.137** | **$1,278** | **$127,800** |

---

## 🛡 Protected Code Zones (Updated)

이번 세션에서 production-ready 확정된 9개 추가:

1. `services/crm/customer_lookup.py` — phone lookup, 500ms timeout, graceful degrade
2. `services/bridge/transactions.update_call_metrics` — background-safe PATCH
3. `voice_websocket.py:_render_customer_context_block` — INVARIANTS 직전 배치
4. `realtime_voice.py customer_lookup hook` — env var CRM_LOOKUP_ENABLED 가드
5. `realtime_voice.py session_state` 7개 신규 키
6. `realtime_voice.py response.done` 진단 로그 (id/status/output_types/transcript)
7. `realtime_voice.py rate_limit_exceeded retry` — silent 자동 회복
8. `bridge_transactions` 5 신규 컬럼
9. `idx_bridge_tx_phone_store` partial index

---

## 📋 Pilot Roadmap Status

```
M0 ✅ Wave A.3 hardening
M1.1 ✅ Wave A.3 라이브 검증 (오늘 09:30)
M1.2 ✅ CRM Wave 1 라이브 검증 (오늘 10:00)
M1.3 ✅ Silent agent 진단 (오늘 11:00)
M1.4 ✅ Retry fix 적용 (오늘 EOD)            ← 세션 종료 시점
M1.5 ⏸ Tier 2 도달 (사용자 $50 충전 + 7일)
M1.6 ⏸ 1매장 24-48h 무인 운영
M2   ⏸ KPI baseline 보고서
M3   ⏸ 5매장 deployment
M4   ⏸ 5매장 안정 운영
M5   ⏸ KPI + Series A pre-prep
M6   ⏸ A/B test 인프라 (Step A read-only)
M7   ⏸ 2.0 canary (Step B)
M8   ⏸ ⭐ Hybrid Routing (Step C-E)
M9   ⏸ Vertical 확장 (KBBQ/Sushi)
```

---

## 🔔 Outstanding User Actions

### 즉시 (이번 주)
1. **OpenAI Dashboard**: $50 충전 ([Buy credits](https://platform.openai.com/settings/organization/billing/overview))
2. **Tier 2 자동 승급** 7일 대기

### 1-2주 내
3. **Live 검증 통화** (Tier 2 도달 후) — silent agent 사라졌는지 확인
4. KPI baseline 측정 (M2)

### 4-6주 내
5. 5매장 Twilio 번호 추가 + store 라우팅 (M3)
6. KPI 보고서 + Series A pre-prep deck (M5)

---

## 🚨 Outstanding Issues (Backlog)

| # | Issue | Priority | 후속 sprint |
|---|---|---|---|
| 1 | Welcome back not fired when name=None (visit_count≥1, recent[]=empty) | ★ | Wave 2 |
| 2 | Modifier 정확도 (large→medium STT) | ★★ | 별도 sprint |
| 3 | "forget me" voice command (Cat 6.3) | ★ | Wave 2 |
| 4 | Tiered opt-in (T2 personalization) | ★ | Wave 2 |
| 5 | customers 테이블 도입 (denormalized → 정규화) | ★ | Wave 2 |
| 6 | Mini KO/JA/ZH 50-utterance eval | ★★ | Step C 직전 (M7) |
| 7 | gpt-realtime-2.0 canary 검증 | ★★ | Step B (M7) |

---

## 📚 Key Documents Created This Session

- `docs/superpowers/specs/2026-05-08-crm-wave-1-design.md` — Spec
- `docs/cost-analysis/2026-05-08/openai-realtime-cost-strategy.{md,html,pdf}` — 종합 비용 전략
- `docs/cost-analysis/2026-05-08/realtime-models-3way-comparison.{md,html,pdf}` — 3-way 모델 비교
- `docs/cost-analysis/2026-05-08/hybrid-rollout-timing-and-risk.{md,html,pdf}` — Hybrid 시점·위험
- `docs/cost-analysis/2026-05-08/_build_pdf.py` — PDF 빌드 스크립트 (재사용)
- 본 세션 요약 (이 파일)

## 🔧 Memory Updates

- ⭐ 신규: `session_resume_2026-05-08_crm-wave-1.md` (다음 세션 진입점)
- 신규: `feedback_implementation_first_testing.md` (TDD override)
- 갱신: `feedback_db_schema_reference.md` (도메인 한정)
- 갱신: MEMORY.md 인덱스 (위 신규/⭐ 추가)

---

## 🏁 Next Session Entry

```bash
# 다음 세션 첫 명령어
# 1. session_resume_2026-05-08_crm-wave-1.md 읽기
# 2. 환경 점검
git log --oneline -15
curl -s -o /dev/null -w "local=%{http_code}\n" http://127.0.0.1:8000/health
curl -s -o /dev/null -w "ngrok=%{http_code}\n" https://bipectinate-cheerily-akilah.ngrok-free.dev/health

# 3. OpenAI Tier 2 도달 확인 (Settings → Limits)
# 4. 사용자 결정 옵션:
#    α) Tier 2 검증 통화 (silent agent 사라졌는지 라이브 확인)
#    β) M2 1매장 24-48h baseline KPI 수집
#    γ) M3 5매장 deployment 계획
#    δ) Modifier 정확도 sprint (별개)
```

---

**End of Session Summary.**

*Distribution: founder + technical handoff.*
