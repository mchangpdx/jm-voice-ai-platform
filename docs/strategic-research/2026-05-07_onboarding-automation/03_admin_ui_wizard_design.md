# Admin UI Wizard — 매장 Onboarding 자동화 설계

**Date**: 2026-05-07
**Goal**: 새 매장 onboarding을 30시간 (수동) → 2-4시간 (자동)으로 단축. saas-platform repo (JM 관리 콘솔) 작업.

---

## 1. 경쟁사 / 업계 onboarding 패턴 전수 조사

### Restaurant SaaS onboarding 사례

| 솔루션 | 메뉴 입력 방식 | 평균 시간 | 자동화 수준 |
|---|---|---|---|
| **Toast POS** | Manual entry + CSV import + AI menu builder (2024 추가) | 4-8시간 | 중 |
| **Square for Restaurants** | Manual + CSV + Library import | 6-12시간 | 낮 |
| **Lightspeed** | CSV bulk + manual | 8-16시간 | 낮 |
| **Loyverse** | Manual + CSV + bulk edit | 4-8시간 | 낮 |
| **Clover** | Manual + Marketplace apps | 8-20시간 | 낮 |
| **Olo (Ordering)** | API integration with POS | 매장당 1주 | 높 (POS 자동) |
| **ChowNow** | Menu sync with POS + manual review | 2-4시간 | 높 |
| **Maple AI** (경쟁사) | Manual setup + concierge service | 비공개 (NY 풀 팀 추정 8-16시간) | 낮 |

### AI / Voice agent onboarding 사례

| 솔루션 | 패턴 |
|---|---|
| **Retell AI** | Agent template + manual prompt + tool config. 30분-2시간 setup, 그러나 매장 customize 별도. |
| **Vapi** | Agent builder UI + tool integrations. 1-3시간. |
| **Bland.ai** | Pathway (script tree) + voice + variables. 1-4시간. |
| **Voiceflow** | Drag-drop conversation flows. 4-12시간 (복잡 카탈로그). |

### 일반 SaaS Wizard 패턴 (참고)

- **Stripe Connect**: 6-step onboarding, 진행률 표시, 단계별 저장
- **Shopify**: Multi-step + 광고/리포트 미리보기
- **Notion**: Template gallery + customize
- **Linear**: Workspace setup wizard (5 steps, 5분 완료)

### 업계 best practice 요약
1. **Multi-step wizard with save-and-resume**: 운영자가 한 세션에 다 못 끝내도 됨
2. **Template gallery start**: vertical 선택 → 80% prefill
3. **POS auto-import + AI assist**: 메뉴 입력 자동화의 결정적 수단
4. **Live preview**: 운영자가 "내 매장에서 봇이 이렇게 응답할 것" 미리 확인
5. **Test call / dry run**: 진짜 라이브 전 시뮬레이션 통화

---

## 2. JM Tech One Admin UI Wizard — 6-Step UX Flow

### Step 1: Vertical 선택

**UI**: Card grid — 큰 카드 6개

```
┌─────────────────────────────────────────────────────────┐
│  🏪 매장 종류를 선택하세요                                │
├─────────────────────────────────────────────────────────┤
│  ☕ Cafe          🥩 Korean BBQ    🍣 Japanese Sushi    │
│  EN/ES/KO/JA/ZH   EN/KO            EN/JA                │
│                                                          │
│  🥡 Chinese       🌮 Mexican       🍔 Other Restaurant   │
│  EN/ZH            EN/ES            EN + custom           │
└─────────────────────────────────────────────────────────┘
```

**Behind the scenes**:
- Vertical 선택 → `backend/app/templates/{vertical}/` 모든 default load
- DB: `stores.vertical = '...'`, `stores.languages = [...]`

### Step 2: POS 연동 (또는 Manual)

**UI**: 3-way choice + setup form

```
어떻게 메뉴를 가져오시겠어요?

┌──────────────────────┬──────────────────────┬──────────────────────┐
│ 📲 POS 자동 동기화    │ 📤 PDF/이미지 업로드 │ ✏️ 직접 입력          │
│                       │                      │                      │
│ Loyverse / Quantic   │ AI가 OCR + 구조화    │ Template 부터 시작    │
│ / Square / Toast     │ 후 검토 가능          │ — 18 메뉴 미리 채워짐 │
│                       │                      │                      │
│ ⚡ 5분 — 권장          │ 🤖 15분               │ 🐢 1시간               │
└──────────────────────┴──────────────────────┴──────────────────────┘
```

**Behind the scenes**:
- POS sync: Loyverse API token / Quantic OAuth → menu + modifier_groups + modifiers fetch
- PDF upload: Claude Vision OCR → structured menu_items list
- Manual: Template 18-meu (cafe) 또는 vertical 별 default 채워짐

### Step 3: 메뉴 검토 + 알러젠 / 다국어 자동 추론

**UI**: 좌측 메뉴 리스트 + 우측 detail edit

```
┌─────────────────┬───────────────────────────────────────────┐
│  메뉴 (18 items) │  📝 Cafe Latte                              │
│  ─────────────  │                                             │
│  ☕ Cafe Latte   │  English: [Cafe Latte                    ] │
│  ☕ Cappuccino   │  Korean:  [카페 라떼  🤖 AI 제안           ] │
│  ☕ Mocha        │  Japanese:[カフェラテ 🤖 AI 제안           ] │
│  🥐 Croissant    │  Spanish: [Café con leche 🤖             ] │
│  🥐 Almond       │  Chinese: [拿铁          🤖              ] │
│     Croissant ⚠️ │                                             │
│  ...             │  Base price (small): $5.50                 │
│                  │                                             │
│  [+ 새 메뉴 추가] │  Allergens (auto-inferred):                │
│                  │  ☑ dairy (whole milk)  🤖 90% confidence    │
│                  │  ☐ gluten              ☐ wheat              │
│                  │  ☐ nuts                ☐ soy                │
│                  │  💡 AI 추천 근거: "Milk-based espresso"      │
│                  │                                             │
│                  │  [✓ 검토 완료] [⟳ AI 다시 추천]              │
└─────────────────┴───────────────────────────────────────────┘

⚠️ Almond Croissant — nuts 알러젠 confidence 95% — 확인 필요
```

**Key UX**:
- AI 추론 결과는 **체크박스 미리 체크** 상태로 보여줌 — 운영자는 "검토 완료" 버튼만 누르면 됨
- 다국어 alias는 LLM이 자동 채우고 운영자가 잘못된 것만 수정
- 알러젠 confidence < 80% 인 항목은 ⚠️ 표시
- "Almond Croissant" 같은 명백한 nuts 항목은 confidence 95% 자동 체크

### Step 4: Modifier 검토 + 매장 customize

**UI**: Vertical default modifier + 매장 추가/수정

```
┌─────────────────────────────────────────────────────────────┐
│  Modifier Groups (Cafe vertical default)                    │
├─────────────────────────────────────────────────────────────┤
│  ✓ Size           Required, 1 only      [Edit prices]       │
│      Small ($0)  Medium (+$0.50)  Large (+$1.00)            │
│                                                              │
│  ✓ Milk           Optional for milk drinks                  │
│      Whole, 2%, Skim, Oat (+$0.75), Almond, Soy, Coconut    │
│      ⚠️ Oat = adds gluten/wheat allergen                      │
│      ⚠️ Almond = adds nuts allergen                           │
│                                                              │
│  ✓ Syrup          Optional, 0-3                              │
│      Vanilla, Hazelnut (nuts!), Caramel, Lavender, ...       │
│                                                              │
│  + 새 modifier group 추가                                     │
│                                                              │
│  [📋 매장 운영 시 알러젠 dynamic 계산 활성화 ✓]              │
└─────────────────────────────────────────────────────────────┘
```

**Key UX**:
- Vertical default 8 group 미리 펼쳐짐 — 운영자는 가격만 customize
- "Oat milk = gluten/wheat 추가" 같은 알러젠 영향 명시 (식품안전 교육 효과)
- 추가 modifier 신규 정의 가능

### Step 5: 매장 페르소나 + Live Preview

**UI**: 매장 정보 입력 + 시뮬레이션 통화

```
┌──────────────────────────┬──────────────────────────────────┐
│  매장 정보                │  🎙️ Live Voice Preview            │
│  ──────────                │                                   │
│  매장명: [JM Cafe       ] │  봇 페르소나 미리보기:             │
│  영업시간:                │  "Hi, this is Aria from JM Cafe.  │
│   [Mon-Sun 7AM-9PM     ] │   How can I help you today?"      │
│  위치:                    │                                   │
│   [Portland, OR        ] │  [▶️ 시뮬레이션 통화 시작]            │
│  특별 안내:               │                                   │
│   [Free WiFi, Parking ] │  💡 매장 운영자가 직접 통화해서      │
│                           │     봇 응답 미리 확인 가능            │
│  Tier-3 매니저 알림:      │                                   │
│  📧 manager@jmcafe.com   │  지난 5번 응답 quality:             │
│  📱 +15035551234         │  ✅ 메뉴 정확도 100%                  │
│  (캐리어 SMS gateway)     │  ✅ 알러젠 정확도 100%                │
│                           │  ⚠️ 다국어 응답 80% (한국어 통과)     │
└──────────────────────────┴──────────────────────────────────┘
```

**Behind the scenes**:
- System prompt = `{{vertical}}/system_prompt_base.txt` + 매장 페르소나 변수 inject
- Live preview = 임시 Twilio 번호 또는 web mic 시뮬레이션
- 5번의 quality check 자동 시뮬레이션 (typical scenarios)

### Step 6: 라이브 활성화

**UI**: Final review + go-live checklist

```
┌─────────────────────────────────────────────────────────────┐
│  ✅ 활성화 전 체크리스트                                      │
├─────────────────────────────────────────────────────────────┤
│  ✓ 메뉴 18개 등록됨                                          │
│  ✓ 알러젠 매핑 100% (운영자 확인)                            │
│  ✓ 다국어 alias 5개 언어 모두 채워짐                         │
│  ✓ Modifier groups 8개 정의됨                                │
│  ✓ Tier-3 매니저 연락처 등록                                 │
│  ✓ Test call 1건 통과 (영문 happy path)                      │
│  ⚠️ Test call (한국어) 미실시 — 권장                          │
│  ✓ Twilio 번호 매핑 확인 (+1-503-994-1265)                   │
│                                                              │
│  [🚀 GO LIVE — 매장 활성화]                                   │
│                                                              │
│  💡 활성화 후 24시간 모니터링 자동 활성화. 회귀 발생 시       │
│     자동 알림 + 즉시 비활성화 옵션.                          │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 기술 스택 옵션 비교 (10점 만점)

| 항목 (10점) | A. saas-platform 확장 (React + Express) | B. 별도 admin app (Next.js 신규) | C. backend admin API + jm-voice-ai-platform 추가 페이지 |
|---|:---:|:---:|:---:|
| 기존 인프라 재사용 | **9** | 5 | 7 |
| 개발 속도 | 8 | 6 | **9** |
| 유지보수 단순성 | **9** | 6 | 7 |
| 매장 운영자 접근성 (이미 saas-platform 로그인) | **10** | 5 | 6 |
| Multi-tenant 격리 (이미 RLS 있음) | **9** | 7 | 8 |
| 디자인 일관성 | **9** | 6 | 7 |
| 결제/구독 통합 | **9** | 6 | 5 |
| 영업측 데모 가치 | **9** | 7 | 6 |
| 미래 확장 유연성 | 8 | **9** | 7 |
| **합계 / 90** | **80** | **57** | **62** |

→ **옵션 A (saas-platform 확장) 압도적 우위**. 이미 매장 운영자가 saas-platform에서 dashboard 보고 있음. Onboarding wizard를 같은 곳에 두는 것이 자연스럽다.

---

## 4. 구현 단계 (Phase 8 — 2-3주, saas-platform 작업)

### Week 1 — Backend admin APIs

신규 endpoints in `backend/app/api/admin/`:
- `POST /api/admin/onboarding/start` — wizard session 시작
- `POST /api/admin/onboarding/{session_id}/menu/import` — POS sync trigger
- `POST /api/admin/onboarding/{session_id}/menu/upload` — PDF/image upload + OCR
- `POST /api/admin/onboarding/{session_id}/allergens/infer` — AI 추론 호출
- `POST /api/admin/onboarding/{session_id}/aliases/generate` — 다국어 자동 생성
- `POST /api/admin/onboarding/{session_id}/preview/simulate` — voice preview
- `POST /api/admin/onboarding/{session_id}/activate` — go-live (DB commit + Twilio 라우팅)

### Week 2 — saas-platform UI (React)

- 6-step wizard component
- POS sync flow (Loyverse OAuth UI)
- 메뉴/modifier/알러젠 검토 UI (drag-drop, AI suggestion 강조)
- Live preview 컴포넌트 (web mic simulation)
- Multi-language alias editor

### Week 3 — End-to-end 검증 + JM BBQ 첫 매장 onboarding

- JM BBQ 첫 매장을 wizard로 onboarding (시간 측정)
- 목표: 30시간 → 4시간 검증
- 회귀 + 라이브 통과 + 운영자 피드백 수집

---

## 5. 자동화 도구 ROI (재계산)

| Phase | 매장 누적 | 수동 시간 | 자동화 시간 | 절감 (h) | 1인 월 작업량 (160h 기준) |
|---|---|---|---|---|---|
| Phase 1 | 5 | 170h | 20h | 150h | 0.94 month |
| Phase 2 | 30 | 1,020h | 120h | 900h | 5.6 months |
| Phase 3 | 80 | 2,720h | 320h | 2,400h | 15 months |
| Phase 4 | 200 | 6,800h | 800h | 6,000h | 37.5 months |
| Phase 5 | 500 | 17,000h | 2,000h | 15,000h | **94 months (8명 풀타임 12개월)** |

**Wizard 구축 비용**: 2-3주 (1인) = 80-120 hours

**Break-even point**: 5매장 (Phase 1 완료 시점) — 즉 자동화 도구가 자기 비용을 회수하는 시점.

**Phase 3 (80 매장) 시점**: 절감 시간이 자동화 도구 구축의 **20배 이상**. 이건 단순 "있으면 좋은" 기능이 아니라 **사업 확장의 핵심 엔진**.

---

## 6. 경쟁 우위 측면 — Maple과의 비교

| 항목 | Maple AI | JM Tech One (Wizard 도입 후) | JM 우위 |
|---|---|---|---|
| 매장 onboarding 시간 | 8-16h (NY 풀 팀 수동) | **2-4h (자동)** | **4-8x 빠름** |
| 매장당 onboarding 비용 | $400-800 (팀 시간) | $50-100 (운영 자동) | **5-8x 저렴** |
| 100매장 시점 운영 인력 | 5-10명 추정 | **2명 (현재 2인 팀)** | **2.5-5x 효율** |
| 다국어 매장 지원 | 4 lang max | **5 lang (KO + JA wedge)** | **차별화** |
| Vertical-specific 패키지 | 한정 (restaurant 위주) | **5+ vertical template** | **차별화** |

→ **Maple이 자본력으로 인력 채용해서 따라잡으려 해도 unit economics 면에서 구조적 열위**. Wizard = JM의 "Solo+AI lean" 우위를 시스템화.

---

## 7. 위험 / 한계 / 완화

| 위험 | 영향 | 완화 방안 |
|---|---|---|
| AI 추론 부정확 (알러젠 false-negative) | 식품안전 critical | (a) 운영자 검토 필수 단계, (b) confidence < 90% 항목 ⚠️ 표시, (c) 운영자가 confirm 안 하면 활성화 못 함 |
| POS sync 실패 (Loyverse API 변경 등) | 부분 매장 onboarding 지연 | Manual 입력 fallback 항상 활성화 |
| 다국어 alias 어색함 | 고객 경험 저하 | LLM 추천 + 운영자 검토 + 통화 후 quality 모니터링 |
| 매장 운영자가 wizard 어려워함 | 채용 burden | 영업 측이 첫 매장 지원, 그 후 self-serve |
| Multi-tenant data isolation 버그 | 보안 critical | RLS 강제 (CLAUDE.md 규칙) + admin API 전수 audit |
| Live preview 비용 (시뮬레이션 통화 OpenAI cost) | 매장당 onboarding $1-3 | Cache 적용, 표준 시나리오 미리 녹음 |

---

## 8. 전문가 최종 의견

### 핵심 메시지

**"Admin UI Wizard는 'nice to have'가 아니라 사업 확장의 결정적 엔진"** — Phase 2 (30매장) 진입 전 반드시 완성. 그렇지 않으면:
- 30매장 = 1,020시간 = 6개월 풀타임 → 영업/개발 모두 마비
- Maple이 자본력으로 NY 팀 확장하면 그쪽이 빠를 가능성 — 우리 unfair advantage 사라짐

### 우선순위 권장

| 순위 | 작업 | 근거 |
|---|---|---|
| 🥇 | **Phase 7-A: JM Cafe template 추출 + JM BBQ 어댑터** (이번 작업) | Wizard의 backend 기반. Template 없이 wizard 못 만듦. |
| 🥈 | **Phase 7-B: AI 추론 helper backend prototype** | 3일-1주, prototype 가능. ROI 즉시 측정. |
| 🥉 | **Phase 8: Admin UI Wizard saas-platform 작업** | Phase 7 완료 후 2-3주. JM BBQ 어댑터로 첫 검증. |
| 4 | Phase 9: JM Sushi 어댑터로 wizard 시간 측정 + 검증 | 자동화 효과 정량화 |
| 5 | Phase 10: 한국 치킨 + KBBQ #2 — Phase 1 5매장 완성 | Wizard 운영 검증 |

### 단기 (이번 주) 즉시 할 일
- Phase 7-A 시작: `backend/app/templates/` 디렉토리 + Cafe template 추출
- JM Cafe 새 메뉴 SQL 적용
- Modifier system DB schema migration
- Loyverse modifier sync 확장

### 중기 (이번 분기) 목표
- Phase 1 PDX 5매장 모두 라이브
- Wizard prototype 완성 + 1매장 자동 onboarding 시간 측정
- Maple 대비 onboarding 효율 5x 차이 정량 검증

### 장기 (2026 EOY) 목표
- Phase 2 30매장 + Wizard self-serve (영업 측 직접 운영 가능)
- Cash-flow positive
- Pre-seed close 준비

---

## 9. 다음 세션 첫 작업 (구체)

이 분석 + JM Cafe 새 메뉴 SQL 적용을 첫 작업으로:

```bash
# 1. JM Cafe 새 메뉴 SQL 적용 (01번 문서 참조)
.venv/bin/python -c "
from app.core.config import settings
import httpx
# Apply migrate_jm_cafe_real_menu.sql via Supabase REST or direct SQL editor
"

# 2. backend/app/templates/cafe/ 디렉토리 + 첫 파일들
mkdir -p backend/app/templates/cafe
# Create menu.yaml, modifier_groups.yaml, allergen_rules.yaml, system_prompt_base.txt

# 3. Modifier system DB migration (Phase 7-A schema)
# backend/scripts/migrate_modifier_system.sql

# 4. Loyverse modifier sync 확장 (existing menu_sync.py)

# 5. 라이브 검증 — JM Cafe 새 메뉴로 통화 1건
# 시나리오: oat milk latte (gluten/wheat present 검증) + 다국어 한 통
```

이걸 다음 세션 첫 행동으로 진행하면 일주일 안에 JM Cafe production-ready + JM BBQ 어댑터 시작 가능.
