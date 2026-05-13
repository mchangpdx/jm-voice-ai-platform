# Frontend Claude 작업 지시서 — Admin Onboarding Wizard

**대상**: 프론트엔드 작업 담당 (별도 Claude 세션 또는 별도 작업 트랙)
**작성**: 2026-05-12 (백엔드 트랙 공항 세션 중)
**충돌 위험**: **없음** — 백엔드와 다른 디렉토리, 신규 파일만 추가, 기존 admin/agency 화면 미변경

> **업데이트 (2026-05-12 EOD)**: 백엔드 endpoint **3개가 이미 라이브** (`/extract`, `/normalize`, `/preview-yaml`). 더 이상 mock 안 써도 됨 — 처음부터 real fetch로 작업 가능. base URL은 `https://jmtechone.ngrok.app` 또는 dev에서 `http://localhost:8000`. `/finalize`만 아직 mock 필요 (백엔드 Phase 4-5 작업 중).

---

## 0. 한 줄 요약

매장 owner가 **Loyverse 토큰 / 메뉴 사진 / URL / CSV / 수동입력** 중 하나만 제공하면, 6단계 wizard를 거쳐 voice agent까지 자동 활성화하는 **Admin UI Wizard**를 만드세요. 백엔드는 이미 입력→정규화→menu.yaml 까지 동작합니다(데모 가능). 프론트엔드는 **mock data로 시작**하고, 백엔드가 endpoint를 제공하면 연결만 갈아끼우면 됩니다.

---

## 1. 작업 범위 (충돌 없는 새 파일만)

### 새로 만들 디렉토리
```
frontend/src/views/admin/onboarding/
├── OnboardingWizard.vue          # 6-step container (라우터 진입점)
├── steps/
│   ├── Step1_SourceUpload.vue
│   ├── Step2_AIPreview.vue
│   ├── Step3_EditItems.vue
│   ├── Step4_ModifierReview.vue
│   ├── Step5_POSSync.vue
│   └── Step6_TestCall.vue
├── components/
│   ├── ItemRow.vue               # confidence 뱃지 + inline edit
│   ├── ConfidenceBadge.vue       # 0-100% 색상 시각화
│   ├── SourceTypeToggle.vue      # Loyverse/URL/Photo/CSV/Manual 선택
│   └── WizardStepper.vue         # 진행도 헤더
└── api/
    ├── onboardingClient.ts       # POST /api/admin/onboarding/* wrapper
    └── mockOnboarding.ts         # 백엔드 미준비 동안 사용할 fixture
```

### 절대 건드리지 말 것
- `frontend/src/views/admin/` 이미 존재하는 파일들 (login, dashboard 등)
- `frontend/src/views/agency/` — 별도 트랙
- `frontend/src/views/{homecare,retail,fsr}/`
- `backend/**` — 백엔드 트랙 작업 중
- `docs/**` — 이 지시서 외에는 새 문서 없이 진행

### Router 등록
`frontend/src/router/index.ts` (또는 동등 라우터 정의 파일) **에 한 줄만** 추가:
```ts
{ path: "/admin/onboarding/new", component: () => import("@/views/admin/onboarding/OnboardingWizard.vue") }
```
다른 라우트는 건드리지 마세요.

---

## 2. API Contract (백엔드 합의 — Frozen until 2026-05-15)

백엔드가 endpoint를 제공할 때까지 `mockOnboarding.ts` 가 같은 shape으로 응답합니다.

### POST `/api/admin/onboarding/extract`  *(✅ live)*
**Body**:
```ts
{
  source_type: "loyverse" | "url" | "pdf" | "image" | "csv" | "manual";
  payload: {
    api_key?: string;             // loyverse
    url?: string;                 // url
    image_paths?: string[];       // pdf/image (백엔드 업로드 후 path 반환)
    file_path?: string;           // csv
    items?: Array<{ name: string; price: number; category?: string }>; // manual
  };
}
```
**200 Response** (`RawMenuExtraction`):
```ts
{
  source: "loyverse" | "url" | "image" | "csv" | "manual";
  items: Array<{
    name: string;
    price: number;
    category: string | null;
    description: string | null;
    size_hint: string | null;
    pos_item_id: string | null;
    pos_variant_id: string | null;
    sku: string | null;
    stock_quantity: number | null;
    detected_allergens: string[] | null;
    confidence: number;          // 0.0 - 1.0
  }>;
  detected_modifiers: string[];
  vertical_guess: "pizza" | "cafe" | "kbbq" | "sushi" | "mexican" | "general" | null;
  warnings: string[];
}
```

### POST `/api/admin/onboarding/normalize`  *(✅ live)*
**Body**: `{ "items": RawMenuItem[] }` *(주의: `items` 키로 wrap)*
**200 Response** — NormalizedMenuItem[]:
```ts
Array<{
  name: string;
  category: string | null;
  description: string | null;
  pos_item_id: string | null;
  detected_allergens: string[] | null;
  confidence: number;
  variants: Array<{
    size_hint: string | null;
    price: number;
    pos_variant_id: string | null;
    sku: string | null;
    stock_quantity: number | null;
  }>;
}>
```

### POST `/api/admin/onboarding/preview-yaml`  *(✅ live)*
**Body**: `{ items: NormalizedMenuItem[]; vertical: string }`
**200 Response** — `{ menu_yaml: object; modifier_groups_yaml: object }` (둘 다 dict, sort 안 함)

### POST `/api/admin/onboarding/pipeline`  *(✅ live — dev helper, hidden from OpenAPI)*
한 호출로 extract+normalize+preview-yaml 체인 실행. Step 별 검증 안 해도 되는 데모 / smoke test 용.
**Body**: `{ source_type, payload, vertical?: string }` (extract와 동일 + optional vertical override)
**200 Response**: `{ raw_extraction, normalized_items, menu_yaml, modifier_groups_yaml }`

### POST `/api/admin/onboarding/finalize`  *(백엔드 Phase 4-5에서 구현 예정)*
**Body**:
```ts
{
  store_name: string;
  phone_number: string;       // Twilio 번호 매핑용
  manager_phone: string;
  menu_yaml: object;          // preview-yaml 결과 그대로
  loyverse_api_key?: string;  // POS direct push 원할 때만
}
```
**200 Response**: `{ store_id: string; voice_agent_url: string; test_call_number: string }`

---

## 3. 6-Step UX (Plan 문서 기준)

### Step 1 — Source Upload
- **Toggle 5개**: Loyverse token / URL / 메뉴 사진 / CSV / 수동입력
- 각 toggle 별 입력 UI:
  - Loyverse: text input + "Verify" 버튼 (whoami 호출로 매장명 표시)
  - URL: text input + 미리보기 iframe (optional)
  - Photo: drag-drop multiple (presigned S3 또는 백엔드 `/api/admin/upload` — 별도 협의)
  - CSV: drag-drop single file
  - Manual: spreadsheet-like grid (name / price / category)
- "Extract" 버튼 → POST /extract → Step 2

### Step 2 — AI Preview
- `RawMenuExtraction.items` 테이블 렌더링
- 각 row에 `ConfidenceBadge`:
  - 0.95+ : 초록 ✓
  - 0.70–0.94 : 노랑 ⚠
  - <0.70 : 빨강 ❗ (operator review 강조)
- 상단: `vertical_guess` 표시 + "다시 추론" 버튼
- 상단: `warnings[]` 알림 banner
- "Continue → Edit" 버튼

### Step 3 — Edit Items (inline)
- Step 2 표를 inline editable로 (price, name, category, allergens)
- 한 행 삭제 가능
- "Normalize" 버튼 → POST /normalize → Step 4

### Step 4 — Modifier Review
- `detected_modifiers` (size, crust, milk 등) 목록 표시
- 매장 vertical template의 기본 modifier_groups 비교 (백엔드가 Phase 3에서 제공 예정 — 일단 Hard-coded)
- operator 가 modifier group ON/OFF + option 편집
- "Confirm" 버튼

### Step 5 — POS Sync
- "Loyverse direct push" 또는 "CSV export" 선택
- 진행 표시 (progressbar) — 카테고리 → modifier_groups → options → items 순
- 백엔드 Phase 4-5 완료 전에는 mock으로 진행도만 시뮬레이션

### Step 6 — Test Call
- 큰 버튼: "Twilio test call now"
- 클릭 → 백엔드가 outbound 콜 trigger (해당 endpoint도 Phase 5)
- 통화 결과 실시간 로그 (WebSocket 또는 polling)
- "완료" 클릭 → `/admin/dashboard` 로 redirect

---

## 4. 디자인 가이드

### 스타일
- 기존 admin 화면 (`views/admin/`)의 디자인 토큰 재사용
- 색상: dark blue (`#1e40af`) primary, amber (`#b45309`) emphasis — 이미 시스템 표준
- 폰트/spacing: 기존 `views/admin/Dashboard.vue` (또는 동등 파일) 참조

### 컴포넌트 라이브러리
- 기존에 쓰던 그대로 (확인 필요). 새 라이브러리 도입 금지.
- 만약 기존 Vue 컴포넌트 없으면 plain `<div>`/`<button>` + CSS modules.

### 다국어
- Step 라벨, 버튼 텍스트는 **영어 + (한국어 보조)** — 백엔드 코드 컨벤션과 동일
- 예: `"Extract menu items (메뉴 추출)"`

---

## 5. Mock Data (`mockOnboarding.ts`)

백엔드 endpoint 준비 전까지 같은 shape으로 응답하세요. 가장 쉬운 fixture는 **JM Pizza Loyverse 라이브 결과**:

```ts
// 24 items after normalize, vertical='pizza'
// 백엔드 검증된 데이터 — copy from
// backend/tests/unit/services/onboarding/test_normalizer.py
// (test_jm_pizza_live_data_folds_34_rows_to_24_items 케이스)
```

`extract()` 호출은 1.5초 setTimeout 후 mock 반환 (실제 API 체감 모사).
`normalize()`는 즉시 반환.
`finalize()`는 5초 진행도 시뮬레이션.

---

## 6. 백엔드 트랙과의 동기화 절차

1. **이 지시서를 수령하면**: 현재 backend feature 브랜치 (`feature/openai-realtime-migration`) 의 최신 5 commits 확인하지 마세요 — backend 진척에 신경 쓸 필요 없습니다.
2. **새 브랜치**: `feature/onboarding-wizard-ui` (또는 동등). main에서 분기.
3. **PR 시점**: Step 1-3 까지 mock으로 완성되면 1차 PR. Step 4-6은 백엔드 Phase 4-5 완료 후 2차 PR.
4. **API contract 변경 요청**: 만약 위 shape이 UI 관점에서 불편하면, 이 지시서 끝부분에 "FE FEEDBACK"으로 추가하세요. 백엔드 다음 세션에서 반영.

---

## 7. 절대 하지 말 것

- 백엔드 endpoint 호출 시도 (아직 안 만들었습니다 — 호출하면 404 또는 500)
- `frontend/src/services/api.ts` (또는 기존 API client) 의 base URL/auth 로직 수정
- 기존 admin 화면의 navigation/sidebar 구조 변경
- `backend/**` 변경 — 백엔드 트랙이 작업 중
- 새 npm 패키지 추가 (필요하면 사용자에게 먼저 확인)

---

## 8. 완료 조건 (Step 1-3 1차 PR)

- [ ] `/admin/onboarding/new` 라우트 진입 가능
- [ ] 5개 source type 모두 Step 1 입력 UI 동작
- [ ] mock data로 Step 2 AI Preview 렌더링 (confidence 색상 구분 보임)
- [ ] Step 3 inline edit 후 NormalizedMenuItem 상태로 다음 단계 진입
- [ ] Step 4-6 은 placeholder ("백엔드 준비 중") 페이지로 OK
- [ ] 기존 admin 화면 회귀 없음 (login, dashboard 정상)
- [ ] `npm run build` 성공
- [ ] PR description에 스크린샷 3장 (Step 1, 2, 3)

---

**Hand-off ready.** 백엔드 트랙은 modifier_groups extractor + allergen inference + Phase 4 db_seeder 로 계속 갑니다.
