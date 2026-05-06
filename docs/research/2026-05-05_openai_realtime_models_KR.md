# OpenAI Realtime 모델 — JM Tech One 마이그레이션 종합 리서치

**날짜:** 2026-05-05  |  **분석:** smb-voice-agent-researcher  |  **대상:** JM Tech One 창업자 (2인 팀, 포틀랜드 본사)  |  **의사결정 컨텍스트:** Retell + Gemini 3.1 Flash Lite → OpenAI Realtime 직접 마이그레이션

---

## 요약 (Executive Summary)

2026-05-05 시점 OpenAI Realtime API는 세 모델로 정리됨: **`gpt-realtime-1.5`** (플래그십, 2026-02-23 출시), **`gpt-realtime`** (2025-08-28 GA), **`gpt-realtime-mini`** (저가 변형, 스냅샷 `2025-10-06` / `2025-12-15`). 레거시 `gpt-4o-realtime-preview*` 계열은 2025-09에 6개월 deprecation 통지 → 2026-03 종료(이미 지남). 가격은 풀 모델 audio in/out **$32/$64 per 1M**, mini는 약 **$10/$20 per 1M** (~3배 저렴)에서 안정화됨. JM Tech One의 단일 매장(JM Cafe) 파일럿 + 8개 voice tool + idempotent guard + Asian-SMB 확장 시나리오에 대해 권장: 프로덕션은 **`gpt-realtime-1.5`**, 카나리/회귀 테스트/rate-limit fallback은 **`gpt-realtime-mini`**. `gpt-4o-realtime-preview*` 사용 금지(deprecated). `gpt-realtime-2025-08-28` dated snapshot 신규 고정 비추천 — 1.5는 tool calling 신뢰도(+7% instruction following), 한국어/일본어/중국어 mid-utterance switching, alphanumeric transcription(+10.23%) 모두 측정 가능한 개선. 이 네 가지는 JM의 핵심 통증과 직결됨(레스토랑 주문 정확도 = tool 신뢰도; 전화번호/주문코드 = alphanumeric; 다국어 = Asian-SMB 웨지).

---

## 1. 모델 라인업 — 전수 인벤토리 (2026-05-05)

| 모델 | 스냅샷 | 출시일 | 상태 | 모달리티 | 컨텍스트 | 최대 출력 | 최대 세션 |
|---|---|---|---|---|---|---|---|
| **`gpt-realtime-1.5`** | `gpt-realtime-1.5` (alias), Azure `2026-02-23` | 2026-02-23 | GA, 현행 플래그십 | audio in/out, text, image in | 32K (입력 ~28,672) | 4,096 | 60분 (OpenAI) / 30분 (Azure EU) |
| **`gpt-realtime`** | `gpt-realtime-2025-08-28`, alias `gpt-realtime` (1.5로 floating 가능성) | 2025-08-28 GA | GA, 직전 플래그십 | audio in/out, text, image in | 32K | 4,096 | 60분 |
| **`gpt-realtime-mini`** | `gpt-realtime-mini-2025-12-15`, `gpt-realtime-mini-2025-10-06` | 2025-10-06 / 2025-12-15 | GA, 저가 변형 | audio in/out, text | 모델카드 128K / Realtime 세션 32K 유효 | 4,096 | 60분 |
| **`gpt-4o-realtime-preview-*`** | `2024-10-01`, `2024-12-17`, `2025-06-03` | 2024-10 → 2025-06 | **Deprecated** (~2026-03 종료) | audio in/out, text | 128K | 4,096 | 30분 |
| **`gpt-4o-mini-realtime-preview-*`** | `2024-12-17` | 2024-12 | **Deprecated** (상위 계열 동반) | audio in/out, text | 128K | 4,096 | 30분 |

**음성 (gpt-realtime / 1.5):** `marin`, `cedar` (2025-08 GA에서 신규, Realtime 전용), 레거시 `alloy`, `ash`, `ballad`, `coral`, `echo`, `sage`, `shimmer`, `verse`. Marin/Cedar이 OpenAI 포트폴리오 중 가장 자연스러움.

**미공개 베타/`gpt-realtime-2.0`/`gpt-realtime-pro`** 는 2026-05-05 시점 Azure 모델 레지스트리, OpenAI changelog, 개발자 커뮤니티 어디서도 확인되지 않음. 존재한다면 비공개.

---

## 2. 가격 — 2026-05-05 권위 데이터

USD per 1M tokens. 토큰 환산: **사용자 audio = 1 token / 100ms** (분당 600), **어시스턴트 audio = 1 token / 50ms** (분당 1,200).

| 모델 | Audio in | Audio out | Audio cached in | Text in | Text out | Text cached in |
|---|---|---|---|---|---|---|
| `gpt-realtime-1.5` | $32.00 | $64.00 | $0.40 | $4.00 | $16.00 | $0.40 |
| `gpt-realtime` (2025-08-28) | $32.00 | $64.00 | $0.40 | $4.00 | $16.00 | $0.40 |
| `gpt-realtime-mini` | $10.00 | $20.00 | $0.30 | $0.60 | $2.40 | $0.06 |
| `gpt-4o-realtime-preview-2025-06-03` (deprecated) | $40.00 | $80.00 | $2.50 | $5.00 | $20.00 | $2.50 |
| `gpt-4o-mini-realtime-preview` (deprecated) | $10.00 | $20.00 | $0.30 | $0.60 | $2.40 | $0.30 |

**5분 통화, 80/20 비율 (고객 4분 / 에이전트 1분):**

- 입력: 4분 × 600 = 2,400 토큰 / 출력: 1분 × 1,200 = 1,200 토큰
- gpt-realtime-1.5: (2,400×$32 + 1,200×$64) / 1M = **$0.1536** ≈ **$0.031/분**
- gpt-realtime-mini: (2,400×$10 + 1,200×$20) / 1M = **$0.048** ≈ **$0.0096/분**
- gpt-4o-realtime-preview 레거시: ~$0.038/분 (deprecated)

**캐싱 효과:** 시스템 프롬프트 + tool 스키마(약 5K 토큰)를 적극 캐싱하면 입력 비용 80배 감소($32 → $0.40). 실효 정적 비용은 통화당 무시 수준.

---

## 3. 능력 비교 (1.5 vs GA vs mini)

| 능력 | gpt-realtime-1.5 | gpt-realtime (08-28) | gpt-realtime-mini |
|---|---|---|---|
| Function calling — ComplexFuncBench Audio | 별도 미공개; GA 대비 instruction-following +7% | 66.5% (직전 모델 49.7%) | 미공개; 플래그십 미달 |
| Async function calling | 가능 (세션 흐름 유지) | 가능 | 가능 |
| Parallel tool calls | 가능 | 가능 | 가능 |
| Image input | 가능 | 가능 | 불가 |
| MCP 서버 연결 | 가능 | 가능 | 가능 |
| Semantic VAD (eagerness 파라미터) | 가능 | 가능 | 가능 |
| Server VAD (레거시) | 가능 | 가능 (일부 스냅샷에서 tool use와 충돌 보고됨) | 가능 |
| SIP 지원 | 가능 (2026 전용 SIP IP 추가) | 가능 | 가능 |
| WebRTC / WebSocket | 둘 다 | 둘 다 | 둘 다 |
| 음성 | Marin, Cedar + 레거시 8종 | 동일 | 부분 (Marin/Cedar 일관성 떨어짐) |
| 다국어 mid-utterance switching | GA 대비 향상; 명시 기능 | 가능; 1.5보다 약함 | 가장 약함 |
| Big Bench Audio reasoning | GA 대비 +5% | 기준 | GA 미만 |
| Alphanumeric 인식 | GA 대비 +10.23% (전화번호, 주문코드) | 기준 | 약함 — 전화번호/주문번호 캡처 시 위험 |
| EU 데이터 거주성 | 가능 (`gpt-4o-realtime-preview-2025-06-03` 도) | 가능 (`2025-08-28` 만) | 부분 |
| HIPAA BAA (audio in/out) | 2026 Q1 시점 정식 등재 안 됨 — **법무 검토 필요** | 동일 caveat | 동일 caveat |
| Zero Data Retention (ZDR) | Trust Center 신청 가능; `store=false` + WebSocket 호환 | 동일 | 동일 |

---

## 4. 지연시간, Rate Limit, 운영 한도

- **TTFT / 첫 오디오 청크:** Realtime 계열은 ~250–300ms TTFT. 1.5는 점진적 개선 — 공개 TTFT 회귀 없음. Sendbird "interruption 처리 탁월", Genspark "통화 에러 절반 감소, connection rate 66%로 두 배" 보고.
- **Rate limit (Tier 1):** ~200 RPM, ~40K TPM. Realtime 세션은 별도 회계 (concurrent session 수가 결정적). Tier 5는 ~20K RPM, 15M TPM.
- **동시 Realtime 세션:** 공식적으로 API 키당 ~100 soft cap (커뮤니티 보고). 일부 개발자는 500+ 세션 열림. **100을 hard로 가정, 5매장 SLA 전 stress test 필수.**
- **최대 세션 길이:** OpenAI 60분 / Azure EU 30분. JM Cafe 통화 통상 5분 미만 — 비제약.
- **컨텍스트:** 32K 토큰, 입력 ~28,672. 긴 통화는 클라이언트 측 요약 필요; Realtime API는 자동 압축 안 함.
- **알려진 이슈:**
  - 일부 스냅샷에서 server VAD가 tool use를 깨뜨림 (2026 Q1 보고) — semantic VAD 권장.
  - `gpt-realtime-2025-08-28`에서 transcript 누출 버그 보고 — 해당 dated snapshot 고정 비추천.
  - 다국어: 프랑스어/억양 영어 약함; 한/일/중은 양호하나 완벽하지 않음 — 프롬프트 anchoring 필수.

---

## 5. 다국어 현실 점검

OpenAI는 57개+ 언어 지원을 명시하나 WER <50% 통과 언어만 "지원"으로 표기. JM의 Asian-SMB 확장 관점:

| 언어 | gpt-realtime-1.5 | gpt-realtime GA | mini | 주의 |
|---|---|---|---|---|
| 영어 | 우수 | 우수 | 우수 | 네이티브 |
| 스페인어 | 매우 양호 (alphanumeric 향상) | 매우 양호 | 양호 | PDX Hispanic 시장 가능 |
| 한국어 | 양호 — 1.5 switching 향상 | 사용 가능 | 가장 약함 | 프롬프트로 한국어 anchoring 필수 |
| 일본어 | 양호 | 사용 가능 | 가장 약함 | 동일 |
| 중국어 (Mandarin) | 양호 | 사용 가능 | 가장 약함 | 성조 양호; 관용어 자연스러움 부족 |
| 프랑스어 | 가장 약함 | 가장 약함 | 가장 약함 | 현재 회피 |

**Mid-call language switching** ("English ↔ Korean ↔ English")은 1.5의 핵심 개선이며 GA 대비 명확히 우수. mini는 의미 있게 떨어짐 — 다국어 매장에 prompt 가드레일 없이 mini 배포 금지.

---

## 6. 점수 매트릭스 — JM 의사결정 요소

10점 만점. 가중치는 JM 우선순위 반영: 단일 매장 단계에서 비용은 실재하나 지배적이지 않음; tool 신뢰도 = 존재 위협; 다국어 = Asian-SMB 웨지.

**가중치:** 비용 20%, 지연시간(TTFT/barge-in) 20%, 다국어 switching 25%, Tool/기능 호환성 35%.

| 모델 | 비용 (20%) | 지연 (20%) | 다국어 (25%) | Tool/기능 (35%) | 가중 합계 |
|---|---|---|---|---|---|
| **`gpt-realtime-1.5`** | 7 / 10 | 9 / 10 | 9 / 10 | 10 / 10 | **(7×0.20)+(9×0.20)+(9×0.25)+(10×0.35) = 1.4+1.8+2.25+3.5 = 8.95** |
| **`gpt-realtime` (08-28)** | 7 / 10 | 8 / 10 | 7 / 10 | 9 / 10 | **(7×0.20)+(8×0.20)+(7×0.25)+(9×0.35) = 1.4+1.6+1.75+3.15 = 7.90** |
| **`gpt-realtime-mini`** | 10 / 10 | 8 / 10 | 5 / 10 | 7 / 10 | **(10×0.20)+(8×0.20)+(5×0.25)+(7×0.35) = 2.0+1.6+1.25+2.45 = 7.30** |
| **`gpt-4o-realtime-preview-2025-06-03`** | 4 / 10 | 7 / 10 | 6 / 10 | 6 / 10 | **(4×0.20)+(7×0.20)+(6×0.25)+(6×0.35) = 0.8+1.4+1.5+2.1 = 5.80** |
| **`gpt-4o-mini-realtime-preview`** | 9 / 10 | 7 / 10 | 4 / 10 | 5 / 10 | **(9×0.20)+(7×0.20)+(4×0.25)+(5×0.35) = 1.8+1.4+1.0+1.75 = 5.95** |

**최종 우승: `gpt-realtime-1.5` 8.95/10.** Mini 7.30이 최강 fallback. gpt-4o 레거시 두 변형은 dominated + deprecated — 제외.

---

## 7. 시나리오별 추천

**기준 통화량: 5매장 × 50통화/일 × 5분 × 30일 = 37,500분/월.**

### 시나리오 A — 단일 매장 영어 중심 파일럿 (오늘의 JM Cafe)
- **추천: `gpt-realtime-1.5`** (해당 region에서 미가용 시 alias `gpt-realtime`).
- 1매장 월 비용 (7,500분): ~$0.031/분 × 7,500 = **~$232/월** (캐싱 전). 캐싱 적용 시 $180–$200.
- 이유: 레스토랑 주문 정확도 = 존재 위협. mini와의 비용 차이($72/월)는 1매장 단계에서 function-calling 회귀를 정당화 못 함.

### 시나리오 B — PDX 5매장 확장, Hispanic 비율 高
- **추천: 5매장 모두 `gpt-realtime-1.5`.** 1.5 스페인어는 "매우 양호" + alphanumeric 강 — 스페인어 전화번호 캡처 중요.
- 월 비용: ~$232 × 5 = **~$1,160/월** raw; 캐싱 시 **~$700–$900/월**.
- 이 단계에서 hybrid 비추천 — 운영 복잡도 > 절감액.

### 시나리오 C — Asian-SMB 확장 (한식/일식/중식)
- **추천: `gpt-realtime-1.5`만, 타협 없음.** Mini 다국어 = 최약체, 한국어 웨지 직접 훼손.
- 시스템 프롬프트에 매장 주 언어 명시적 anchoring + `respond_in_language` 지시; 사용자 명시 요청 시에만 switching.
- 월 비용: B와 동일 (볼륨 스케일 전).

### 시나리오 D — 시간당 100통화 스케일
- **추천: `gpt-realtime-1.5` 주 + `gpt-realtime-mini` 오버플로우 라우터.** 통화 시작 시 (caller-ID + 첫 발화 의도 분류기를 text-only Gemini 3.1 Flash Lite 또는 mini로) 의도 사전 분류 → FAQ/영업시간/메뉴 조회 = mini, 예약/주문/결제 = 1.5.
- Hybrid ROI: 40%가 mini로 라우팅되면 blended cost $0.031/분 → ~$0.022/분 (~30% 절감). 100 통화/시간 × 8시간 × 5분 = 4,000분/일 = 120K분/월, 절감 ~$1,080/월.
- 운영 caveat: hybrid는 fail-mode 2개 추가(라우터 오류, mini→플래그십 핸드오프). 5매장에서 1.5-only가 안정된 후에만 구축.

### Hybrid mini ↔ 플래그십 라우팅 — 활성화 조건
- 볼륨 임계: >50K분/월 (5매장 유기적 성장 초과).
- 라우팅 신호: 첫 2초 오디오 의도 분류기 + caller history.
- Fallback: mini의 function-call 신뢰도가 임계치 미만이면 1.5로 mid-session hot-swap (현 API의 `session.update`로 모델 swap 가능).

---

## 8. 마이그레이션 의사결정 트리

```
POC (Week 0–2): gpt-realtime-mini
  → 이유: 가장 싸게 fail-fast (WebRTC/SIP, Twilio TCR, 오디오 패스스루,
    idempotent guard 검증). 전송 버그를 잡는 동안 tool 품질 차이는 병목 아님.

회귀 테스트 (Week 2–4): gpt-realtime-1.5
  → 이유: 기존 Retell+Gemini 통화 코퍼스 replay. 1.5가 production target —
    실제 ship할 모델 대비 회귀 diff 측정.

카나리 (Week 4–6): gpt-realtime-1.5 (5–10% 트래픽)
  → 이유: 프로덕션 모델과 동일해야 카나리 신호 명확.
  → 행동 surprise로 rollback isolation 필요할 때만 dated snapshot 핀; 그 외엔
    floating alias `gpt-realtime-1.5` 사용.

풀 프로덕션 (Week 6+): gpt-realtime-1.5 (floating alias)
  → 이유: floating alias는 향후 개선(`gpt-realtime-1.6`, `2.0`) 자동 수령.
    OpenAI deprecation cadence가 6개월로 안정적 — 허용 가능 위험.
  → daily smoke-test로 drift 감지.

Rate-limit / 429 Fallback: gpt-realtime-mini
  → 이유: 3배 저렴, Realtime 세션 프로토콜 동일, drop-in 호환. 품질 저하는
    가시적이나 통화는 완료됨.
  → Realtime 클라이언트 측 retry + model swap으로 구현; mini를 silent 서빙
    금지 (반드시 로깅).

개발/테스트 비용 최적화: gpt-realtime-mini
  → 이유: 비고객 테스트 ~70% 저렴. 프로덕션 테스트는 여전히 1.5.
```

---

## 9. JM 스택 통합 훅

- **Tool 스키마 캐싱:** 8개 voice tool (`create_order`, `modify_order`, `cancel_order`, `make_reservation`, `modify_reservation`, `cancel_reservation`, `allergen_lookup`, `recall_order`)을 세션 시작 시 안정적 ID로 1회 정의. 캐시 입력 $0.40/M에서 통화당 tool 재주입 비용 무시 가능.
- **Idempotent guard:** OpenAI Realtime에 변경 불필요 — function call의 `call_id` semantics 보존. 현재 idempotency 레이어 (RLS-tenanted `tenant_id` + tool args hash dedup key) 그대로 유지.
- **RLS 격리:** `tenant_id`를 세션 스코프 변수로 전달; 모델에 노출 금지. 모든 tool 호출에서 서버 측 강제 (현 패턴).
- **Semantic VAD `eagerness=low`:** 예약 read-back 등 긴 어시스턴트 턴에서 조기 interruption 감소.
- **Twilio TCR + SIP:** OpenAI가 2026에 전용 SIP IP 범위 추가 (`sip.api.openai.com` GeoIP 라우팅) — PSTN 지연 최소화 위해 WebRTC 브릿징보다 직접 SIP 권장.
- **음성 선택:** `marin`은 영어 기본 매장(따뜻함); `cedar`는 활발한/젊은 demo. 한국어 자연스러움은 두 음성 모두 테스트 필요 — 커뮤니티 보고 엇갈림.
- **Allergen tool (Tier 3 EpiPen 핸드오프):** 1.5의 향상된 instruction-following이 Tier 3 hard-stop을 보존하는지 카나리 acceptance gate에 추가.

---

## 10. 리스크 & 워치리스트

1. **HIPAA 갭:** OpenAI Realtime audio in/out은 2026 Q1 Azure 명확화 기준 정식 BAA 범위 미포함. 레스토랑 스코프는 PHI 미발생이나 향후 약국/클리닉 인접 vertical 진입 시 재평가.
2. **Transcript 누출 버그** in `gpt-realtime-2025-08-28` — 해당 정확 snapshot 핀 회피. floating `gpt-realtime` 또는 `gpt-realtime-1.5` 직행.
3. **Server VAD ↔ tool use 충돌** in 일부 snapshot — JM tool surface는 semantic VAD 기본.
4. **동시 세션 ceiling** 모호 — 5매장 rollout SLA 약속 전 load-test 확정.
5. **Floating alias drift** — 향후 모델 bump (예: 1.6)이 JM tool 패턴에 회귀할 수 있음. daily smoke-test로 완화; 분기별 snapshot 핀 검토.
6. **Mini의 한국어/일본어 품질** — 부하 시에도 Asian-SMB 통화를 mini로 라우팅하지 말 것; 플래그십 429 retry 우선.

---

## 11. 출처

1. [OpenAI — Introducing gpt-realtime](https://openai.com/index/introducing-gpt-realtime/) — GA 발표, 2025-08-28; 가격, ComplexFuncBench 66.5%, Marin/Cedar 음성.
2. [OpenAI Platform — gpt-realtime model card](https://platform.openai.com/docs/models/gpt-realtime) — 스냅샷, 모달리티.
3. [OpenAI Platform — gpt-realtime-mini model card](https://platform.openai.com/docs/models/gpt-realtime-mini) — 컨텍스트, 모달리티, cost tier.
4. [OpenAI Developers — gpt-realtime-1.5 model card](https://developers.openai.com/api/docs/models/gpt-realtime-1.5) — 1.5 스펙.
5. [Perplexity — OpenAI releases gpt-realtime-1.5 for voice AI developers](https://www.perplexity.ai/page/openai-releases-gpt-realtime-1-uvxkVAujTJKQFr1N8we4Tg) — 2026-02-23 출시 확인; +7% instruction-following, +10.23% alphanumeric, +5% Big Bench Audio.
6. [OpenAI API Pricing](https://openai.com/api/pricing/) — 권위 가격.
7. [Azure OpenAI Foundry — model availability](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/realtime-audio) — 2025-08-28, 2025-10-06, 2025-12-15, 2026-02-23 버전 확인.
8. [OpenAI Developers — Deprecations](https://developers.openai.com/api/docs/deprecations) — gpt-4o-realtime-preview deprecation.
9. [OpenAI Realtime VAD guide](https://platform.openai.com/docs/guides/realtime-vad) — semantic VAD eagerness.
10. [OpenAI Developer Community — gpt-realtime-2025-08-28 transcript leakage bug](https://community.openai.com/t/bug-realtime-api-transcript-returns-other-users-data-and-internal-tokens-gpt-realtime-2025-08-28/1369978) — 알려진 이슈.
11. [OpenAI Developer Community — Realtime languages](https://community.openai.com/t/languages-in-realtime-api/980149) — 57+ 언어 리스트, 정확도 노트.
12. [OpenAI Developer Community — multilingual challenges](https://community.openai.com/t/challenges-in-multilingual-understanding-with-realtime-apis/991453) — 프랑스어 약점, language drift.
13. [Sprinklr — Benchmarking gpt-realtime](https://www.sprinklr.com/blog/voice-bot-gpt-realtime/) — 독립 음성 에이전트 벤치.
14. [InfoQ — gpt-realtime production-ready](https://www.infoq.com/news/2025/09/openai-gpt-realtime/) — 기능 분석.
15. [Microsoft Q&A — HIPAA eligibility of Realtime audio](https://learn.microsoft.com/en-us/answers/questions/5616040/clarification-request-hipaa-eligibility-of-azure-o) — 2026 시점 HIPAA 갭.
16. [Microsoft Q&A — Realtime 30-min session](https://learn.microsoft.com/en-us/answers/questions/5741275/gpt-realtime-maximum-session-length-30-minutes) — Azure EU 세션 ceiling.
17. [GitHub — openai/openai-realtime-agents issue #119](https://github.com/openai/openai-realtime-agents/issues/119) — 세션 길이 관리 패턴.
18. [Forasoft — Realtime API WebRTC/SIP/WebSocket integration](https://www.forasoft.com/blog/article/openai-realtime-api-webrtc-sip-websockets-integration) — 전송 매트릭스.
19. [eesel — gpt-realtime-mini pricing](https://www.eesel.ai/blog/gpt-realtime-mini-pricing) — 독립 분당 분석.
20. [Hacker News — GPT-Realtime-1.5 Released](https://news.ycombinator.com/item?id=47129942) — 1.5 신뢰도 커뮤니티 신호.
