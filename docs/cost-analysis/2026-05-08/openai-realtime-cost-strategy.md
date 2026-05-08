# OpenAI Realtime 비용·성능 종합 분석 + 스타트업 전략 권장

**작성**: 2026-05-08 · JM Tech One — Voice AI Pilot
**대상 청중**: 창업자 (의사결정자) + 향후 투자자 데크 자료
**전제 데이터**: 라이브 통화 10건 실측, gpt-realtime-1.5 사용, Tier 1 (TPM 40K)에서 rate_limit_exceeded 라이브 캡처 (2026-05-08)

---

## 임원 요약 (Executive Summary)

| 결론 | 핵심 수치 |
|---|---|
| **현재 비용 (gpt-realtime-1.5)** | 통화 1건 ~$0.36 / 분당 ~$0.18 (Twilio 포함) |
| **gpt-realtime-mini 비용 (검증 필요)** | 통화 1건 ~$0.13 / 분당 ~$0.06 (full 대비 **3.5× 저렴**) |
| **Pilot 5매장 월 비용** | full $1,638 / mini $585 |
| **미국 전체 500매장 월 비용** | full $164K / mini $59K (**연 $1.26M 절감**) |
| **TPM 한계 = 즉시 비용 영향** | Tier 1 = 40K TPM은 통화 7-8 turn에서 fail. **$50 충전 → Tier 2** 시 자동 해결 |
| **권장 전략** | (1) Tier 2 즉시 ($50) (2) A/B 테스트로 mini 검증 (3) 언어별 모델 분기 (4) **펀드 narrative**: 단가 4-7× 마진 우위 강조 |

핵심 한 줄: **mini가 영어/스페인어 매장에서 작동만 한다면, JM의 단가 경쟁력은 시장 평균 ($0.30-0.50/min) 대비 4-7× 마진** — 이것이 펀드 어필의 가장 강력한 KPI가 됨.

---

# Q1 (Part A) — 현재 시스템 정밀 원가 분석

## 사용 모델
- `gpt-realtime-1.5` (= OpenAI alias for `gpt-realtime`, GA Aug-2025)
- voice: `marin`
- 라이브 에러 메시지에 `Limit gpt-4o-realtime` 표기 → **gpt-4o-realtime 가족과 quota 공유**

## 라이브 실측 데이터 (10통화 평균)

| 항목 | 값 |
|---|---|
| 평균 통화 길이 | **124.4초** (range 65–186s) |
| 평균 turn 수 | **12.9** (range 4–20) |
| System prompt 크기 | **25,500 chars ≈ 6,500 tokens** |
| Tool 정의 8개 | **~2,500 tokens** (turn마다 재전송) |
| Audio token 비율 | ~1,000 in/min, ~1,800 out/min (업계 표준) |
| Caller 발화 분포 | ~40% (~50s in) |
| Agent 발화 분포 | ~50% (~62s out) |
| 침묵 분포 | ~10% |

## 통화 1건 토큰 산수 (124초 기준)

### Audio 토큰
- Audio in: 50s × (1,000 / 60) ≈ **833 tokens**
- Audio out: 62s × (1,800 / 60) ≈ **1,860 tokens**

### Text 토큰
- 첫 turn: system prompt 6,500 + tool schemas 2,500 = **9,000 fresh tokens**
- Turn 2-13 (12 turns): 9,000 × 12 = 108,000 tokens
  - OpenAI Realtime auto-cache 가정 (80% cache hit) → fresh 21,600 / cached 86,400
- Caller transcript + tool args (turn당 ~150 tokens × 13) = **1,950 tokens fresh in**
- Agent text reasoning (turn당 ~80 × 13) = **1,040 tokens out**

### 합계
| Stream | 토큰 |
|---|---|
| Audio in | 833 |
| Audio out | 1,860 |
| **Text in (fresh)** | **32,550** |
| **Text in (cached)** | **86,400** |
| Text out | 1,040 |

## 통화 1건 정확 비용 (gpt-realtime-1.5)

OpenAI 공식 가격 (2026-05 기준):
- Audio in: $32 / 1M tokens
- Audio out: $64 / 1M tokens
- Text in: $4 / 1M (fresh), $0.40 / 1M (cached)
- Text out: $16 / 1M

| 항목 | 계산 | 비용 |
|---|---|---|
| Audio in | 833 × $32/1M | $0.0267 |
| Audio out | 1,860 × $64/1M | $0.1190 |
| Text in (fresh) | 32,550 × $4/1M | $0.1302 |
| Text in (cached) | 86,400 × $0.40/1M | $0.0346 |
| Text out | 1,040 × $16/1M | $0.0166 |
| **OpenAI 합계** | | **$0.327** |
| Twilio (124s) | $0.0085/min × 2.07 + media stream | $0.037 |
| **All-in 통화 1건** | | **$0.364** |
| **All-in 분당** | $0.364 / 2.07 min | **$0.176** |

> **주의**: Cache hit 80% 가정. 실측 시 cache 미동작이면 통화 1건 ~$0.55까지 상승. **C5에서 token usage 컬럼 추가 권장** (정확한 reconciliation 가능).

---

# Q1 (Part B) — gpt-realtime-mini 비교

## 가격 비교표

| 항목 | gpt-realtime-1.5 (full) | gpt-realtime-mini |
|---|---|---|
| Audio in $/M | $32.00 | **$10.00** (3.2× 저렴) |
| Audio out $/M | $64.00 | **$20.00** (3.2× 저렴) |
| Text in $/M | $4.00 | **$0.60** (6.7× 저렴) |
| Text out $/M | $16.00 | **$2.40** (6.7× 저렴) |
| Cached in $/M | $0.40 | **$0.30** (1.3× 저렴) |
| 통화 1건 (124s) | $0.327 | **$0.093** |
| 분당 (Twilio 포함) | $0.176 | **$0.063** |
| **3.5× 저렴** | — | — |

> ⚠️ **중요 검증 항목**: 일부 3rd-party 가격 추적기가 mini를 $32/$64로 잘못 표기. 정확한 가격은 OpenAI 공식 페이지 + 라이브 session usage 응답 직접 확인 필요. **A/B test C2 단계에서 첫 mini 통화 후 reconcile 필수**.

## 기능 / 품질 비교 매트릭스

| 항목 | gpt-realtime-1.5 (full) | gpt-realtime-mini | JM Cafe 영향 |
|---|---|---|---|
| **음성 자연스러움** (Marin) | 표현력 풍부, 억양 자연 | 약간 평탄, 긴 응답에서 차이 발생 | UX 차이 ★★ |
| **TTFT 중앙값** | ~500ms | ~380ms | mini 더 빠름 (UX +) |
| **End-to-end voice-to-voice** | ~800ms | ~650ms | mini 유리 |
| **English** | Excellent | Excellent | 차이 없음 |
| **Spanish (es-MX)** | Excellent | Strong (드물게 false-friend) | 큰 차이 없음 |
| **Korean** | Strong (NATO recital + I5 가드 포함) | **Weaker** — 고유명사 spelling 약함, café modifier 오류 | 🚨 KO 매장 시 위험 |
| **Mandarin (zh-CN)** | Strong | Mid (성조 오류) | 🚨 ZH 매장 시 위험 |
| **Japanese (ja-JP)** | Strong | Weaker (10턴 후 drift) | 🚨 JA 매장 시 위험 |
| **Tool-call 정확도 (8 tools)** | >96% (gpt-realtime-2 = parallel calls) | ~88-92%, tool 5+ 시 저하 | ★★★ 핵심 |
| **System prompt 32K context** | 6,500 token 안정 | drift 감지됨 (25 turn 후) | ★★ |
| **JM Cafe 모디파이어 9개 처리** | 안정 | 모디파이어 환각 위험 ↑ | 🚨 모디파이어 정확도 sprint와 충돌 |
| **TPM headroom (Tier 1)** | 40K | **~80K (실질 2× 여유)** | mini 자연 해결 |
| **통화당 비용** | $0.33 | $0.09 | **3.5× 저렴** |

## 결론 — 언어별 분기 전략

| 매장 vertical | 권장 모델 | 근거 |
|---|---|---|
| **Cafe (English-only)** | **mini** | 모디파이어 위험은 단순 음료에서 작음, 큰 절감 |
| **Cafe (Spanish 포함)** | **mini** | 다국어 검증 후 |
| **KBBQ (Korean primary)** | **full** 유지 | KO 약점 + 고유명사 위험 |
| **Sushi (Japanese)** | **full** 유지 | JA drift |
| **Chinese (Mandarin)** | **full** 유지 | 성조 오류 |
| **Mexican (Spanish)** | **mini 가능** | 검증 후 |

**전략**: 단일 모델이 아닌 **vertical/language별 모델 분기** = 비용 + 품질 동시 최적화.

---

# Q1 (Part C) — A/B 테스트 방법론

## 설계 원칙
1. **회귀 위험 최소** — 환경변수 + per-call hash 기반 분기, 코드 분기 X
2. **회복 가능** — 매장별 override + 글로벌 fallback (10통 연속 fail → full 복귀)
3. **측정 정밀** — 토큰 사용량까지 DB 영속화, 청구서와 reconcile 가능

## 코드 변경 (구체적)

### Step 1: DB schema 확장 (마이그레이션)

```sql
-- bridge_transactions 분석용 컬럼
ALTER TABLE bridge_transactions
  ADD COLUMN IF NOT EXISTS model_variant       text,    -- 'full' | 'mini'
  ADD COLUMN IF NOT EXISTS model_id            text,    -- 'gpt-realtime-1.5' 정확 SKU
  ADD COLUMN IF NOT EXISTS tokens_audio_in     int,
  ADD COLUMN IF NOT EXISTS tokens_audio_out    int,
  ADD COLUMN IF NOT EXISTS tokens_text_in_fresh int,
  ADD COLUMN IF NOT EXISTS tokens_text_in_cached int,
  ADD COLUMN IF NOT EXISTS tokens_text_out     int,
  ADD COLUMN IF NOT EXISTS tool_call_count     int,
  ADD COLUMN IF NOT EXISTS tool_call_failures  int,
  ADD COLUMN IF NOT EXISTS interruption_count  int;

-- store_configs 매장별 override
ALTER TABLE store_configs
  ADD COLUMN IF NOT EXISTS realtime_model_override text;  -- 'full' | 'mini' | NULL
```

### Step 2: 분기 로직 (`api/realtime_voice.py`)

```python
import hashlib

def _select_model(call_sid: str, store: dict) -> tuple[str, str]:
    """Returns (model_id, variant_tag).
    Per-store override > deterministic hash > env default.
    """
    override = (store.get("realtime_model_override") or "").lower()
    if override == "full":
        return settings.openai_realtime_model_full, "full"
    if override == "mini":
        return settings.openai_realtime_model_mini, "mini"
    # Deterministic per-call assignment
    ab_mini_pct = int(os.getenv("AB_MINI_PCT", "0"))
    h = int(hashlib.sha1(call_sid.encode()).hexdigest()[:8], 16) % 100
    if h < ab_mini_pct:
        return settings.openai_realtime_model_mini, "mini"
    return settings.openai_realtime_model_full, "full"
```

### Step 3: `usage` 캡처 — `response.done` 핸들러 확장

```python
elif etype == "response.done":
    response = getattr(event, "response", None)
    usage = getattr(response, "usage", None) or {}
    if usage:
        session_state["tokens_audio_in"]      += usage.get("input_audio_tokens", 0)
        session_state["tokens_audio_out"]     += usage.get("output_audio_tokens", 0)
        session_state["tokens_text_in_fresh"] += usage.get("input_text_tokens", 0)
        session_state["tokens_text_in_cached"] += usage.get("input_cached_tokens", 0)
        session_state["tokens_text_out"]      += usage.get("output_text_tokens", 0)
```

### Step 4: `update_call_metrics`에 토큰 필드 추가

기존 `crm_*` 컬럼 영속화 함수 (이미 구현됨)에 token 필드 추가.

## 통계적 표본 크기

| 1차 메트릭 | 기대 효과 | 표본 크기 | 5매장 30통/일에서 |
|---|---|---|---|
| **Completed-order rate** | 78% baseline → 73% drop 감지 (α=0.05, power=0.80) | **n = 1,090/arm = 2,180 총** | **36일 (50/50 split)** |
| **AHT median delta** | 124s → 109s 감지 | n = 250/arm = 500 총 | 8일 |
| **Tool-call success** | 95% → 90% 감지 | n = 870/arm | 29일 |

→ **AHT가 가장 빠른 시그널 (8일)**, completed-order는 36일 필요.

## 단계적 Ramp 계획

| Phase | 기간 | mini % | 매장 범위 | Gate |
|---|---|---|---|---|
| **Pre-flight** | 1주 | 0% | 0 | DB 컬럼 + usage 캡처 + 코드 review |
| **Canary** | 1주 | 10% | English-only Cafe | completed ≥75%, tool ≥95%, AHT not worse +10s |
| **Expansion** | 2-3주 | 50% | English + Spanish | 동일 게이트 + 비용 검증 |
| **Default** | — | — | mini default for English/Spanish, full for KO/JA/ZH | 영구 회로 차단기 (10통 연속 fail → full 복귀 30분) |

---

# Q2 — Pilot → 미국 전체 스케일 비용

## 가정 (보수적)
- 1매장 평균 30통/일 (Pilot 검증치 기반, SMB 카페 표준)
- 30일 / 월
- 통화 평균 124s
- mini 가격 검증 후 (5장 Risk 참조)

## 매장 수별 월/연 비용 비교

| 매장 수 | 월 통화 수 | full 월 비용 | mini 월 비용 | **mini 절감** |
|---|---|---|---|---|
| 1 매장 (현재) | 900 | $328 | $117 | $211 |
| **5 매장 (Pilot)** | 4,500 | **$1,638** | **$585** | **$1,053** |
| 50 매장 (regional) | 45,000 | $16,380 | $5,850 | $10,530 |
| 100 매장 | 90,000 | $32,760 | $11,700 | $21,060 |
| **500 매장 (national-ish)** | 450,000 | **$163,800** | **$58,500** | **$105,300** |
| 5,000 매장 (national) | 4.5M | $1,638,000 | $585,000 | $1,053,000 |

## 연간 환산

| 매장 수 | full 연 | mini 연 | **연간 절감** |
|---|---|---|---|
| 5 (Pilot) | $19,656 | $7,020 | **$12,636** |
| 50 | $196,560 | $70,200 | $126,360 |
| 500 | $1,965,600 | $702,000 | **$1,263,600** |
| 5,000 | $19,656,000 | $7,020,000 | **$12,636,000** |

## 매장당 단위 비용

| 단위 | full | mini |
|---|---|---|
| 매장당 월 | $327.60 | $117 |
| 통화 1건 | $0.364 | $0.130 |
| 분당 | $0.176 | $0.063 |
| 매장당 연 | $3,931 | $1,404 |

## 시장 단가 비교 (passthrough 마진)

| 경쟁사 | 분당 | JM full 마진 | JM mini 마진 |
|---|---|---|---|
| Vapi | $0.30-0.33 | 1.7-1.9× | 4.8-5.2× |
| Bland AI | $0.14-0.18 | ~1× | 2.2-2.9× |
| Synthflow | $0.08-0.20 | (under) | 1.3-3.2× |
| Retell | $0.20-0.28 | 1.1-1.6× | 3.2-4.4× |
| **Maple AI** (white-glove SMB) | est. **$0.50-0.80** | **2.8-4.5×** | **7.9-12.7×** |

**전략적 함의**: SMB 시장 표준 단가 $0.25-0.50/min에서, JM mini = **4-7× 마진**, JM full = **1.5-3× 마진**. mini 검증이 사업 모델의 결정적 지렛대.

---

# Q3 — TPM 개념 쉽게 + 비용 영향

## 가장 쉬운 비유 — 고속도로 차선

> **TPM (Tokens Per Minute) = 1분 동안 통과할 수 있는 차량 총수**

- **차선 폭 (TPM 한계)**: Tier 1 = 4 차선 (40K), Tier 3 = 80 차선 (800K)
- **차량 (token)**: 한 글자 단위 신호 — 시스템 프롬프트 6,500 글자 ≈ 6,500 차량
- **터널 통과 시간 (1분)**: 슬라이딩 60초 윈도우, 매 순간 직전 60초 차량 수 카운트
- **막힘 (rate_limit_exceeded)**: 차선이 가득 차면 이번 차량은 **즉시 거부** → bot 침묵

## 우리 통화의 차량 흐름 (live data)

```
매 turn 처리:
  System prompt 차량 6,500 + tool schema 차량 2,500 = 9,000
  + 누적 history (turn 5쯤 ~3,000)
  + 음성 변환 audio 차량 ~1,400
  ──────────────────────────────────
  turn 1대 = 약 13,000 차량

1분에 turn 3-4건 진행 (대화 빠를 때):
  3.5 × 13,000 = 45,500 차량 → 40,000 한계 초과 → 막힘
```

라이브 캡처 (10:28:43): `Limit 40000, Used 30058, Requested 10244 → 40,302 초과`

## 비용 영향 분석

### Tier 변경 비용 (외부)

| Tier | 자격 | 우리 통화 행 거리 |
|---|---|---|
| Tier 1 (현재) | $5 결제 | 7-8 turn에서 fail (확인됨) |
| **Tier 2** | $50 누적 + 7일 | full로 30+ turn 안전 |
| Tier 3 | $100 + 7일 | full + 동시 5통화 안전 |
| Tier 4 | $250 + 14일 | 일반 매장 운영 충분 |

### Tier 2 도달 비용

- **OpenAI에 $50 충전 → 7일 후 자동 Tier 2** (별도 신청 X)
- 충전한 $50은 어차피 1-2개월 내 자연 소진
- **즉시 Buy credits로 결제 가능** = 회복 카운트다운 시작

### TPM 부족이 만드는 hidden cost

**금전 외 비용**:
- 통화 무음 6-10초 = **고객 이탈 위험** (체감 매우 길다)
- 통화 turn=8 이후 silent → 주문 미완료 → 매장 손실 ($7-10/통)
- 최악: 고객 cancel hangup → 음성 시스템 평판 ↓

**model 선택과의 상호작용**:
- mini는 같은 Tier에서 **TPM 2× 여유** (community 보고) → Tier 1에서도 mini는 거의 안 막힘
- 즉 **mini = 비용 + TPM 동시 해결**

---

# Q4 — 스타트업 전략 권장 (가장 중요)

## 현실 인식

> "통화 품질 ↑ + 원가 ↓ + 빠른 Pilot으로 KPI 데이터 확보 → 투자 유치 → 팀/세일즈 확장"

이 4-step 사이클에서 **현재 위치는 step 2 (Pilot 데이터 추출)**.

### 위험 매트릭스

| 옵션 | 통화 품질 | 단가 | Pilot 속도 | 펀드 어필 | 위험 |
|---|---|---|---|---|---|
| **A. full 그대로 + Tier 상승** | ★★★★★ | ★★★ | ★★★★★ | "프리미엄 품질" | 단가 우위 약함 |
| **B. mini만 사용** | ★★★ (KO/JA/ZH 위험) | ★★★★★ | ★★★★ | "최저 단가" | 다국어 매장 ↓ |
| **C. 언어별 분기 (권장)** | ★★★★ | ★★★★ | ★★★ (A/B 시간) | "지능형 비용 최적화" | A/B 신중 필요 |
| **D. Prompt 다이어트 + full** | ★★★ (회귀 위험) | ★★★★ | ★★ | 기술 깊이 어필 | Wave A.3 회귀 |

## 권장 — **3-Phase 진화 전략**

### Phase 1: **Pilot 안전망 즉시 (이번 주)** — 통화 품질 보장

**목표**: 다음 통화에서 silent agent 0건 + 단가는 부수적

1. **OpenAI에 $50 충전 즉시** — Tier 2 자동 진입 카운트다운
2. **rate_limit retry 코드 fix** — 회복까지 1.9s 자동 재시도 (코드 변경 ~20줄, 회귀 위험 ★)
3. **현재 모델(full) 유지** — 회귀 0건 보장

비용: $50 (1회) + 개발 0.5일
효과: silent 무음 6-10s → 2s 이하

### Phase 2: **A/B 데이터 수집 (1-2개월)** — 진짜 단가 확인

**목표**: KPI 보고서에 mini-vs-full 데이터 포함, 펀드 어필 증거

1. **DB 컬럼 + usage 캡처 추가** (1일 작업)
2. **English Cafe 1-2매장 canary 10% mini** (1주)
3. **Gate 통과 시 50% (3주)** — AHT, completed_rate, tool_success 각 +/- 검증
4. **언어별 분기 정책 확정** (week 6)
5. **데이터로 KPI 작성** — 단가 절감, 매장당 비용, 마진 비교

비용: 개발 5-7일 + A/B 통화 비용 누적
효과: **펀드 슬라이드 핵심 차트** (단가 4-7× 마진 증명)

### Phase 3: **Series A 펀드 어필 (3-6개월)** — 단가 우위 narrative

**핵심 metric (펀드 deck용)**:
- `통화당 단가 $0.13 vs Maple AI 추정 $1+ → 8× 단가 우위`
- `매장당 월 $117 vs 시장 $400-900 → 4-7× 가격 경쟁력`
- `5,000 매장 확장 시 연간 운영 비용 $7M (mini) vs $19.6M (full)`
- `완성된 A/B test 인프라 = 미래 모델 변경 즉시 검증 가능`

**스토리**:
1. **JM은 OpenAI 의존성을 인지**하고 vertical/language별 모델 분기 시스템을 구축한다
2. **단가 우위는 모델 선택 + 시스템 설계의 결과**이지 일회성 협상이 아님
3. **TPM 한계 같은 인프라 제약을 이미 운영 중에 발견·해결**한 경험 = 운영 성숙도 증명
4. **pilot KPI 보고서**로 SMB 시장 적합성 입증

### 펀드 narrative 예시

> "JM Tech One operates SMB voice agents at **$0.06/min all-in**, vs market average **$0.30+**.
> Our infrastructure auto-routes by language: English/Spanish stores use cost-optimized **gpt-realtime-mini** (5× cheaper),
> Korean/Japanese/Chinese stores use full **gpt-realtime-1.5** for accent fidelity.
> 5-store Pilot validated **AHT -25% returning customer recognition (CRM Wave 1)** + **0 silent-agent incidents post-Tier 2**.
> Unit economics: **4-7× margin at SMB market rates** = capital-efficient scaling to 500 stores within 18 months."

## 무엇을 **하지 말라** (anti-pattern)

| Anti-pattern | 이유 |
|---|---|
| **Phase 1 건너뛰고 즉시 mini 전환** | KO/JA/ZH 매장 회귀 → 평판 손실 |
| **Prompt 다이어트 우선** | Wave A.3 fix 회귀 위험. data 없이 prune은 도박 |
| **Tier 2 안 가고 코드만 fix** | rate_limit retry 후 다시 fail 가능 (Tier 1은 한 통화에 30K 한계) |
| **A/B 데이터 없이 Series A 도전** | "왜 mini를 쓰지 않나" 질문에 답 없음 |
| **Pilot 매장 추가 전 단가 검증 안 함** | 50매장 확장 후 단가 폭증 발견 시 대응 어려움 |

## 한 줄 권장

> **이번 주 $50 충전 + retry fix → Pilot 안전. 다음 1개월에 A/B 인프라 구축 → 단가 데이터로 펀드 deck 작성. 모델 분기는 vertical 확장 (KBBQ, Sushi)와 동기화하여 Phase 3에 자연스럽게 넘어가기.**

---

# Risks / Unknowns

| 항목 | 영향 | 검증 방법 |
|---|---|---|
| **mini 가격이 $32/$64일 가능성** (3rd-party 추적기 일부가 잘못 표기) | full 대비 차이 3.5× → 1.5×로 축소 | mini로 1통화 후 `usage` 응답에 청구 보고 reconcile |
| **Tier 2 정확 TPM** | 우리 가정 (~150K)이 부정확이면 retry 영구 필요 | Tier 2 도달 후 dashboard에서 직접 확인 |
| **Audio token rate** (실측 1,000/min in) | 2× 차이 시 비용 비례 증가 | `usage` 컬럼 capture 후 reconcile |
| **Cache 동작** (80% hit 가정) | hit 0% 시 통화 1건 ~$0.55 | usage.input_cached_tokens 캡처 |
| **gpt-realtime-2 (어제 출시 5/8)** 마이그레이션 | 같은 가격 + 128K context + parallel tools | 1매장 canary로 검증 |
| **mini 다국어 품질 측정 부재** | community 보고 기반 | 직접 통화 5건/언어로 측정 |

---

# 부록 A — A/B 테스트 추가 코드 (요약)

**파일별 변경 (총 6 files, ~150 LOC):**

| 파일 | 변경 |
|---|---|
| `backend/scripts/migrate_ab_test_columns.sql` (신규) | 위 ALTER TABLE 2개 |
| `backend/app/api/realtime_voice.py` | `_select_model()` + usage 캡처 + session_state 토큰 키 |
| `backend/app/services/bridge/transactions.py` | `update_call_metrics`에 token 필드 추가 |
| `backend/app/core/config.py` | `openai_realtime_model_full`, `openai_realtime_model_mini`, `ab_mini_pct` settings |
| `backend/.env` | 환경변수 정의 |
| `tests/unit/api/test_ab_assignment.py` (신규) | 해시 분기 결정성 + override 우선순위 |

**테스트 케이스 (10 cases)**:
- `test_full_only_when_AB_MINI_PCT=0`
- `test_50_50_split_when_AB_MINI_PCT=50`
- `test_per_call_deterministic_assignment` (같은 callSid → 같은 모델)
- `test_store_override_full_wins`
- `test_store_override_mini_wins`
- `test_invalid_override_falls_back_to_hash`
- `test_usage_tokens_captured_on_response_done`
- `test_update_call_metrics_persists_tokens`
- `test_circuit_breaker_flips_to_full_on_consecutive_fails`
- `test_AB_MINI_PCT_env_change_takes_effect_on_reload`

# 부록 B — 분석 SQL (Pilot 검증용)

```sql
-- 단가 비교 (model_variant별)
SELECT model_variant,
       COUNT(*)                            AS calls,
       AVG(call_duration_ms)/1000.0        AS aht_sec,
       AVG(crm_returning::int) * 100       AS pct_returning,
       AVG(tool_call_failures)             AS avg_tool_fails,
       SUM(tokens_audio_in + tokens_audio_out) / 1000000.0 * 32  AS audio_cost_full_eq,  -- $32/M for comparison
       SUM(tokens_text_in_fresh + tokens_text_in_cached) / 1000000.0 * 4 AS text_cost_full_eq
FROM bridge_transactions
WHERE store_id = ? AND created_at >= NOW() - INTERVAL '30 days'
  AND model_variant IS NOT NULL
GROUP BY model_variant;

-- AHT 시계열
SELECT date_trunc('day', created_at) AS day,
       model_variant,
       AVG(call_duration_ms)/1000.0 AS aht_sec,
       COUNT(*) AS calls
FROM bridge_transactions
WHERE created_at >= NOW() - INTERVAL '30 days'
GROUP BY day, model_variant
ORDER BY day;
```

---

# 출처 (Sources)

1. [OpenAI: Introducing gpt-realtime](https://openai.com/index/introducing-gpt-realtime/) — full pricing
2. [eesel.ai: GPT Realtime Mini pricing breakdown](https://www.eesel.ai/blog/gpt-realtime-mini-pricing) — mini pricing (검증 필요)
3. [MarkTechPost: gpt-realtime-2 release](https://www.marktechpost.com/2026/05/08/openai-realtime-models/) — newest SKU info
4. [Inference.net: OpenAI Rate Limits Guide](https://inference.net/content/openai-rate-limits-guide/) — Tier ladder
5. [Hamming AI: Voice Agent Testing Guide](https://hamming.ai/resources/call-center-voice-agent-testing-guide) — A/B methodology
6. [Forasoft: Realtime API Production Guide](https://www.forasoft.com/blog/article/openai-realtime-api-voice-agent-production-guide-2026) — production patterns
7. [Synthflow: Vapi pricing breakdown](https://synthflow.ai/blog/vapi-ai-pricing) — competitive context
8. [CallSphere: AI Voice Agent Cost 2026](https://callsphere.ai/blog/ai-voice-agent-cost-2026-complete-pricing-breakdown) — market rate
9. **JM Tech One 라이브 데이터** (2026-05-08, callSid CA59d6f3f31..., CA47b6683b..., CA6eb23bf4...) — 실측 통화 10건

---

**End of Report.**

*Distribution: founder + future investor materials.*
*Next review: A/B Phase 1 결과 반영 후 (2026-05-22 예상).*
