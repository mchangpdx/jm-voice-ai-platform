# OpenAI Realtime 3-Way 모델 전수 비교 + JM 적합도 점수

**작성**: 2026-05-08 · JM Tech One — Voice AI Pilot
**비교 대상**: `gpt-realtime-2` (신규, 2026-05-08) · `gpt-realtime-1.5` (현재 사용) · `gpt-realtime-mini`
**기준**: 라이브 통화 124s · 12.9 turns · 6,500-token system prompt · Marin voice · 5 언어 (EN/ES/KO/JA/ZH)

---

## 임원 요약 — 한 표로 보는 결론

| 항목 | gpt-realtime-1.5 (현재) | gpt-realtime-2 (신규) | gpt-realtime-mini |
|---|---|---|---|
| **JM 적합도 (0-50)** | **43 / 50** | **42 / 50** | **34 / 50** |
| 통화 1건 비용 | $0.368 | $0.371 (low effort) | $0.113 |
| Audio 가격 | $32 / $64 / 1M | **동일** ($32 / $64) | $10 / $20 |
| Context window | 32K | **128K (4×)** | 32K |
| Tool calling | sequential (현재 silent 위험) | **parallel + audible preamble** | sequential |
| Big Bench Audio | 81.4% | **96.6%** | 미공개 |
| TTFA (응답 시작) | ~500ms | 1.12s @ low | <500ms |
| 1.5 → migration 비용 | — | drop-in (reasoning.effort 추가만) | drop-in (품질 A/B 필요) |
| 다국어 (KO/JA/ZH) 검증 | 라이브 사용 중 | GPT-5-class 추정 | 보고된 약점 |
| **권장 사용처** | **Pilot 안정 운영 (현재 default)** | **canary 검증 후 main 승격** | **English-only cafe A/B (3.5× 비용 절감)** |

> **핵심 한 줄**: 2.0은 audio cost 동일 + 큰 context + parallel tools = **자연스러운 다음 default**. 1.5는 6-12개월 deprecation 예측. mini는 vertical 별 cost 옵션.

---

# Part 1 — Master Spec Table

| 항목 | gpt-realtime-2 | gpt-realtime-1.5 | gpt-realtime-mini |
|---|---|---|---|
| **Status** | GA (2026-05-08 발표) | GA (2025-08-28 snapshot) | GA |
| **Snapshot** | gpt-realtime-2 | gpt-realtime-2025-08-28 | gpt-realtime-mini |
| **Context window** | **128,000 tokens** | 32,000 tokens | 32,000 tokens |
| **Max output** | 32,000 | 4,096 | 4,096 |
| **Modalities (in/out)** | text + audio + image / text + audio | 동일 | 동일 |
| **Voices** | Marin, Cedar (+ legacy 8) | Marin, Cedar (+ legacy 8) | Marin/Cedar 공유 풀 (미문서화) |
| **Audio formats** | pcm16 24kHz, g711_ulaw, g711_alaw | 동일 | 동일 |
| **VAD** | server_vad + semantic_vad | 동일 | 동일 |
| **Transports** | WebRTC + WebSocket + SIP | 동일 | 동일 |
| **Function calling** | **parallel + async + 청취 가능 preamble** | sequential / async | sequential (parallel 미검증) |
| **Reasoning effort** | minimal / low / medium / high / xhigh (default: low) | n/a | n/a |
| **Image input** | Yes | Yes | Yes |
| **MCP support** | Yes | Yes | 제한적 |
| **Big Bench Audio** | **96.6% (high)** | 81.4% | 미공개 |
| **Audio MultiChallenge** | **48.5% (xhigh)** | 34.7% | 미공개 |
| **Scale APR** (instruction 유지) | **70.8%** | 36.7% | 미공개 |
| **TTFA (응답 시작)** | 1.12s @ low / 2.33s @ high | ~500-800ms | <500ms |
| **Knowledge cutoff** | 2024+ (GPT-5-class) | Sep 30, 2024 | Oct 1, 2023 |
| **Tier 1 TPM/RPM** | 40K / 200 | 40K / 200 | 40K / 200 |
| **Tier 2 TPM/RPM** | 200K / 400 | 200K / 400 | 200K / 400 |

## 가격표 (per 1M tokens)

| Token type | gpt-realtime-2 | gpt-realtime-1.5 | gpt-realtime-mini |
|---|---|---|---|
| **Audio input** | $32.00 | $32.00 | **$10.00** |
| Audio cached input | $0.40 | $0.40 | $0.30 |
| **Audio output** | $64.00 | $64.00 | **$20.00** |
| Text input | $4.00 | $4.00 | $0.60 |
| Text cached input | $0.40 | $0.40 | $0.06 |
| **Text output** | $24.00 (+50%) | $16.00 | $2.40 |
| Image input | $5.00 | $5.00 | n/a |

**핵심 발견**: 2.0의 **audio I/O는 1.5와 완전 동일**. 텍스트 출력만 +50% (reasoning trace 과금). 우리 통화 패턴에서 텍스트 출력은 ~1,200 tokens/call이라 비용 차이 미미.

---

# Part 2 — 통화 1건 정확 비용 (3-way)

기준 데이터 (라이브 측정):
- 평균 통화: 124s
- 평균 turns: 12.9
- Audio in: 37,200 tokens (~62s × 600 t/s)
- Audio out: 37,200 tokens
- Text in (fresh): 16,770 tokens
- Text in (cached): 67,080 tokens (80% hit ratio)
- Text out: 1,200 tokens (tool calls + agent reasoning)

## 모델별 비용 분해

| 항목 | gpt-realtime-1.5 | gpt-realtime-2 (low) | gpt-realtime-mini |
|---|---|---|---|
| Text in fresh (16,770 × $4 / $4 / $0.60) | $0.067 | $0.067 | $0.010 |
| Text in cached (67,080 × $0.40 / $0.40 / $0.06) | $0.027 | $0.027 | $0.004 |
| Audio in (37,200 × $32 / $32 / $10) | $1.190 | $1.190 | $0.372 |
| Audio out (37,200 × $64 / $64 / $20) | $2.381 | $2.381 | $0.744 |
| Text out (1,200 × $16 / $24 / $2.40) | $0.019 | $0.029 | $0.003 |
| Reasoning preamble overhead (2.0 only) | — | +$0.018 | — |
| **Subtotal (per 1M math)** | $3.684 | $3.712 | $1.133 |
| **÷ 1000 = per call** | **$0.368** | **$0.371** | **$0.113** |
| Twilio 추가 (2.07 min) | $0.037 | $0.037 | $0.037 |
| **All-in 통화 1건** | **$0.405** | **$0.408** | **$0.150** |
| **All-in 분당** | **$0.196** | **$0.197** | **$0.072** |

## 5매장 Pilot 월 비용

| 모델 | 월 통화 4,500 | 절감률 |
|---|---|---|
| gpt-realtime-1.5 (현재) | $1,823 | baseline |
| gpt-realtime-2.0 | $1,836 | +0.7% (무시할 수준) |
| gpt-realtime-mini | $675 | **-63%** ($1,148 절감/월) |

> **2.0 대 1.5는 비용 사실상 동일** — 비용은 결정 인자가 아님. 품질/안정성/migration 위험만 비교.

---

# Part 3 — JM 적합도 점수 매트릭스 (0-5점, 10개 항목)

## 점수 기준
- **5점**: JM 요구사항 완벽 충족, 추가 작업 없이 사용 가능
- **4점**: 충족하지만 minor 검증/조정 필요
- **3점**: 사용 가능하지만 명확한 단점 존재
- **2점**: 큰 위험 또는 회귀 가능성
- **1점**: 사용 불가 (deal-breaker)
- **0점**: 미지원

## 종합 점수표

| 항목 | gpt-realtime-1.5 | gpt-realtime-2 | gpt-realtime-mini |
|---|---|---|---|
| 1. 비용 효율성 | 4 | 4 | **5** |
| 2. 음성 품질 (Marin) | **5** | **5** | 4 |
| 3. 응답 latency (TTFA) | **5** | 3 | **5** |
| 4. Tool calling (8 tools) | 4 | **5** | 2 |
| 5. Long-context (6,500 prompt) | 3 | **5** | 2 |
| 6. 다국어 (EN/ES/KO/JA/ZH) | 4 | 4 | 2 |
| 7. 안정성 / Production 검증 | **5** | 3 | 3 |
| 8. Migration 비용 (1.5 기준) | **5** (no-op) | 4 | 4 |
| 9. Pilot 진입 속도 | **5** | 4 | 3 |
| 10. Future-proofing (수명) | 3 | **5** | 4 |
| **합계 (0-50)** | **43** | **42** | **34** |

---

# Part 4 — 항목별 상세 점수 + 사유

## 1. 비용 효율성 (cost per call)

| 모델 | 점수 | 사유 |
|---|---|---|
| **1.5** | **4** | $0.368/call. 시장 평균 $0.30+ 대비 적당. SMB 마진 1.7-2.8× |
| **2.0** | **4** | $0.371/call (실질 동일). +50% text-out은 우리 사용 패턴에서 +$0.01에 불과 |
| **mini** | **5** | $0.113/call. 3.5× 저렴. 5,000매장 확장 시 연 $12.6M 절감 |

## 2. 음성 품질 (voice naturalness, Marin support)

| 모델 | 점수 | 사유 |
|---|---|---|
| **1.5** | **5** | Marin 공식 지원. 라이브 운영에서 자연스러움 검증 |
| **2.0** | **5** | Marin/Cedar 공식. GPT-5-class 표현력 향상 |
| **mini** | **4** | "shared voice pool" 통해 Marin 사용 가능 (community 보고). 긴 응답에서 약간 평탄. 공식 문서에 voices 미명시 |

## 3. 응답 latency (TTFA — time to first audio)

| 모델 | 점수 | 사유 |
|---|---|---|
| **1.5** | **5** | ~500-800ms TTFA. 라이브 측정 TTFT 832-2504ms (call 따라 다름) |
| **2.0** | **3** | 1.12s @ low effort (~600ms 더 느림). 2.33s @ high. **단**, parallel tool call 시 audible preamble로 체감 무음 감소 |
| **mini** | **5** | <500ms 일관 보고. 모델 작아서 decoding 빠름 |

## 4. Tool calling (우리 8 tools 환경)

| 모델 | 점수 | 사유 |
|---|---|---|
| **1.5** | **4** | 8 tools 안정 작동 (라이브 검증). 단, sequential only — modify+recall 등 multi-step 시 latency 누적 |
| **2.0** | **5** | **parallel + async + audible preamble** = "checking that for you" 발화 동시에 tool 실행. 우리 modify_order + recall_order 흐름 핵심 개선. Big Bench Audio 96.6% |
| **mini** | **2** | community 보고 8 tools 시 정확도 88-92% 저하. 우리 tool 수가 한계점 근처 |

## 5. Long-context handling (system prompt 6,500 tokens)

| 모델 | 점수 | 사유 |
|---|---|---|
| **1.5** | **3** | 32K context. 6,500 prompt + 12.9 turns × ~2,000 = 약 25K — **여유 7K**. INVARIANTS recency placement 등 fix 필요 |
| **2.0** | **5** | **128K context**. 우리 prompt 무한 확장 가능. Scale APR 70.8% = repair/edit 견고 |
| **mini** | **2** | 32K + 미니 모델 → 6,500 prompt에서 drift 가능 (community 보고). 우리 INVARIANTS 룰 약화 위험 |

## 6. 다국어 fidelity (5개 언어)

| 모델 | 점수 | 사유 |
|---|---|---|
| **1.5** | **4** | EN/ES Excellent, KO/JA/ZH Strong. 라이브 운영 검증. NATO recital 등 커스터마이징 가능 |
| **2.0** | **4** | GPT-5-class — 언어 능력 향상 추정되나 **공식 KO/JA/ZH 벤치마크 부재**. 검증 필요 |
| **mini** | **2** | 영어/스페인어 strong. **KO/JA/ZH 약점 보고됨** — 고유명사 spelling, 성조 오류, 10턴+ 후 drift. KBBQ/Sushi/Chinese 매장 사용 위험 |

## 7. 안정성 / production 검증

| 모델 | 점수 | 사유 |
|---|---|---|
| **1.5** | **5** | 9개월 production 운영. Wave A.3 hardening 완료. 라이브 매장 검증 |
| **2.0** | **3** | **2026-05-08 (어제) 출시**. production 데이터 1일 미만. 잠재 회귀 위험 |
| **mini** | **3** | GA 상태이나 voice agent 사용 사례 적음. 가격 우선 selection 위험 |

## 8. Migration 비용 (1.5 기준)

| 모델 | 점수 | 사유 |
|---|---|---|
| **1.5** | **5** | 현재 default — migration 0 |
| **2.0** | **4** | drop-in compatible. `reasoning.effort: "low"` 추가 + reasoning token 빌링 신규 변수. 코드 변경 ~5줄 |
| **mini** | **4** | drop-in compatible. **품질 검증 A/B 필수** (KO/JA/ZH 등 회귀 위험) |

## 9. Pilot 진입 속도

| 모델 | 점수 | 사유 |
|---|---|---|
| **1.5** | **5** | 이미 운영 중. retry fix만 추가하면 silent 해결 |
| **2.0** | **4** | env var 변경 + canary 1매장으로 즉시 시작. parallel tool call이 silent agent 자연 해결 |
| **mini** | **3** | A/B test 인프라 필요 (DB 컬럼, hash 분기, gate). 4-6주 소요 |

## 10. Future-proofing (모델 수명)

| 모델 | 점수 | 사유 |
|---|---|---|
| **1.5** | **3** | OpenAI 패턴: 신규 모델 GA 후 6-12개월 내 deprecation 예상. 마이그레이션 부담 발생 |
| **2.0** | **5** | 최신 model — 향후 12-18개월 default. 즉시 채택 시 deprecation 사이클 1번 회피 |
| **mini** | **4** | 가격 옵션 라인 — 향후 mini-2.0 등 출시 가능하나 mini라인 자체는 유지 예상 |

---

# Part 5 — 모델별 핵심 사용 시나리오 (recommendation)

## 1.5 → 즉시 안정 운영 default
**언제**: 지금 즉시. retry fix + Tier 2 도달까지.
**근거**:
- 안정성 5/5
- 라이브 매장 검증 완료
- migration 비용 0

**액션**:
1. ✅ rate_limit_exceeded retry 코드 추가 (이번 commit)
2. ✅ Tier 2 자동 승급 ($50 누적 spend 후)

## 2.0 → canary 1매장 즉시 시작
**언제**: retry fix 후 1주 이내
**근거**:
- audio 비용 동일
- parallel tool calls = modify+recall 자연 개선
- 128K context = 향후 prompt 확장 여유
- Future-proofing 5/5

**액션**:
1. `OPENAI_REALTIME_MODEL=gpt-realtime-2` 환경변수로 canary 1매장
2. `reasoning.effort: "low"` 추가
3. AHT, TTFA, tool_call_success 측정 (1주)
4. Gate: 동일/우월하면 main으로 승격, 1.5는 fallback 유지

## mini → English-only Cafe A/B (Phase 2)
**언제**: 1.5/2.0 안정화 후 (4-6주 후)
**근거**:
- 비용 5/5 (3.5× 저렴)
- 영어/스페인어 매장에서 충분한 품질
- KBBQ/Sushi/Chinese에는 적합도 낮음

**액션**:
1. DB schema (model_variant 컬럼)
2. hash-based per-call 분기 (env var AB_MINI_PCT=10 → 50)
3. completed_order_rate ≥75%, tool_success ≥95% gate
4. **언어별 분기 정책 확정**: EN/ES → mini default, KO/JA/ZH → full 유지

---

# Part 6 — 통합 권장 — 3-Phase 진화 전략

## Phase 1: 즉시 안정 (이번 주)
- **모델**: 1.5 유지
- **변경**: retry fix 코드 commit + $50 충전
- **효과**: silent agent 무음 6-10s → 2s

## Phase 2: 2.0 canary 검증 (다음 1-2주)
- **모델**: 1매장 → 2.0 canary
- **변경**: env var 변경 + reasoning.effort
- **메트릭**: AHT, TTFA, parallel tool call 작동 검증
- **결정 게이트**: 1주 후 모든 매장으로 확장 OR 1.5 유지

## Phase 3: mini hybrid routing (1-2개월)
- **모델**: vertical/language별 분기
- **변경**: A/B 인프라 + store_configs.realtime_model_override
- **효과**: 영어/스페인어 매장에서 비용 3.5× 절감
- **펀드 narrative**: "language-tiered model routing for capital-efficient scaling"

---

# Part 7 — Risks / Unknowns

| 항목 | 영향 | 검증 방법 |
|---|---|---|
| **2.0 KO/JA/ZH 품질 미검증** | 다국어 매장 회귀 가능 | 50-utterance per-language eval (canary) |
| **2.0 reasoning token 빌링** | 통화 비용 +5-10% (low) ~ +30% (high) | low 고정 + usage 모니터링 |
| **2.0 TTFA 1.12s** vs 1.5 500ms | 첫 응답 600ms 늦음 | parallel tool preamble로 체감 시간 감소 검증 |
| **mini Marin voice 품질** | UX 약간 평탄 | A/B 테스트 시 사용자 만족도 surrogate (cancel rate) |
| **mini 8 tools 정확도** | tool_call_failures ↑ | A/B에서 실측 |
| **1.5 deprecation timeline 미발표** | 강제 migration 시점 불명 | OpenAI 발표 모니터링 |
| **2.0 첫날 production 위험** | 미발견 회귀 | canary 단일 매장 + 24시간 모니터링 |

---

# Part 8 — 최종 권장 (한 줄)

> **단기 (이번 주)**: 1.5 + retry fix + Tier 2.
> **중기 (1-2주)**: 2.0 canary 1매장 (audio 비용 동일 + parallel tool calls = silent agent 자연 해결 + 향후 default).
> **장기 (1-2개월)**: 영어/스페인어 매장 mini hybrid routing (3.5× 비용 절감 펀드 narrative).
>
> **하지 말 것**: 2.0을 모든 매장 즉시 전환 (안정성 3/5) / mini를 KO/JA/ZH 매장에 적용 (다국어 2/5) / 1.5에 안주 (deprecation 위험)

---

# 출처 (Sources)

1. [TheNextWeb: OpenAI launches GPT-Realtime-2 (2026-05-08)](https://thenextweb.com/news/openai-gpt-realtime-2-voice-models)
2. [OpenAI API Docs: gpt-realtime-2](https://developers.openai.com/api/docs/models/gpt-realtime-2)
3. [OpenAI API Docs: gpt-realtime-1.5](https://developers.openai.com/api/docs/models/gpt-realtime-1.5)
4. [OpenAI API Docs: gpt-realtime-mini](https://developers.openai.com/api/docs/models/gpt-realtime-mini)
5. [OpenAI: Introducing gpt-realtime](https://openai.com/index/introducing-gpt-realtime/)
6. [DataCamp: GPT-Realtime-2 — GPT-5-class reasoning](https://www.datacamp.com/blog/gpt-realtime-2)
7. [Latent Space: GPT-Realtime-2 SOTA voice APIs](https://www.latent.space/p/ainews-gpt-realtime-2-translate-and)
8. [Latent Space: Realtime API Missing Manual](https://www.latent.space/p/realtime-api)
9. [OpenAI API Pricing](https://developers.openai.com/api/docs/pricing)
10. [Microsoft Learn: GPT Realtime API token rates](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/realtime-audio)
11. [eesel.ai: GPT realtime mini practical guide](https://www.eesel.ai/blog/gpt-realtime-mini)
12. [MarkTechPost: Three Realtime Audio Models 2026-05-08](https://www.marktechpost.com/2026/05/08/openai-releases-three-realtime-audio-models)
13. **JM Tech One 라이브 데이터** (callSid CA59d6f3f31..., CA47b6683b..., CA6eb23bf4..., 2026-05-08) — 통화 10건 실측

---

**End of Report.**

*Distribution: founder + technical due-diligence material.*
*Next review: 2.0 canary 1주 결과 반영 시점.*
