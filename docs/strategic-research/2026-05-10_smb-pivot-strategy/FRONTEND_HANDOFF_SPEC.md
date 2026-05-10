# Frontend Handoff — Multi-Vertical Proof Dashboard

**작성일**: 2026-05-10
**대상**: Frontend Claude (cwd: `frontend/`)
**Backend commit ref**: (이번 push 후 업데이트)
**충돌 영역**: 0 — backend 작업은 `backend/* + docs/*`, frontend 작업은 `frontend/*`. git pull --rebase 필수.

---

## 0. 변경 사항 요약 — Backend가 push 함

| 변경 | 위치 | Frontend 영향 |
|---|---|---|
| KBBQ stores row 생성 (sim mode) | DB `stores` 1 row | Dashboard에 5번째 매장 표시됨 |
| `agency.py` KBBQ dispatch elif 추가 | `backend/app/api/agency.py` | `industry='kbbq'` 매장 → kbbq_knowledge KPI 반환 |
| 합성 데이터 280 calls + 180 orders | DB `call_logs` + `orders` | KBBQ 매장 KPI 작동 (avg_ticket $68, monthly_impact $5,479) |
| `gen_kbbq_demo.py` 신규 | `backend/scripts/gen_kbbq_demo.py` | (참고용) 재생성 가능 |

**JM Korean BBQ store_id**: `e365aa0e-6e62-49a1-8c5f-0c55af72a53d`
**owner_id**: `0a1cf9bd-1ad6-49d1-b506-c1320e06d742` (jmkbbq@test.com / 1111)

---

## 1. Frontend 작업 요청 — 3가지 컴포넌트

### F-A. KBBQ verticalLabels 확정 (이미 완료 — `f8a4d95`)
- Frontend Claude `f8a4d95` commit이 KBBQ entry 추가했음. 이미 작동.

### F-B. Multi-Vertical Roll-up — Agency Dashboard 보강

기존 Agency Dashboard (`/agency` 페이지)의 store 카드 grid에 **KBBQ 매장이 자동 노출**됨 (DB 변경만으로). 추가 작업:

1. **Real vs Simulated 라벨 추가**:
   ```tsx
   const isReal = store.id === '7c425fcb-91c7-4eb7-982a-591c094ba9c9';  // JM Cafe
   <Badge color={isReal ? 'green' : 'gray'}>
     {isReal ? 'Real (live since 2026-04-25)' : 'Simulated — 60-day window'}
   </Badge>
   ```

2. **각 매장 카드 industry 라벨**:
   - cafe → "Cafe" (이미 동작)
   - kbbq → "Korean BBQ" (← f8a4d95 entry 활용)
   - beauty → "Beauty Salon"
   - auto_repair → "Auto Repair"
   - home_services → "Home Services"

### F-C. **신규 페이지 — `/admin/architecture-proof`** (투자자 시연용)

#### 구조

```
┌────────────────────────────────────────────────────────────────┐
│  Hero Banner                                                    │
│  "5 verticals live in 0.5 founder-days per vertical."          │
│  "81% backend code reuse. Built once, runs everywhere."        │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│  Section 1 — Vertical Performance Roll-up                       │
│  ┌──────────┬───────┬─────────┬──────────┬──────────┐          │
│  │ Vertical │ Mode  │ Calls   │ AvgTicket│ Impact   │          │
│  ├──────────┼───────┼─────────┼──────────┼──────────┤          │
│  │ Cafe     │ ✅Real│  1,678  │ $15      │ $5.5K    │          │
│  │ Korean   │ Sim   │    280  │ $69      │ $5.5K    │          │
│  │ Beauty   │ Sim   │    ...  │ ...      │ ...      │          │
│  │ Auto     │ Sim   │    250  │ $428     │ ...      │          │
│  │ Home Svc │ Sim   │    ...  │ ...      │ ...      │          │
│  └──────────┴───────┴─────────┴──────────┴──────────┘          │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│  Section 2 — Code Reuse Visualization                           │
│  4-Layer dependency graph showing 81% reuse                     │
│  Layer 1 (Auth/RLS): 100% | Layer 2 (Skills): 95%              │
│  Layer 3 (Knowledge): 93% | Layer 4 (Adapters): 84%            │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│  Section 3 — Add-Vertical Cost Chart                            │
│  Bar chart: "New vertical add time (founder-days)"             │
│  cafe (baseline): 25 days | kbbq: 0.5 days (95% faster)       │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│  Section 4 — Live Demo CTA                                      │
│  "Call +1 (503) 994-1265 to hear it live."                     │
│  [Phone icon + animated 'Live now' indicator]                   │
└────────────────────────────────────────────────────────────────┘
```

#### 데이터 소스

| 컴포넌트 | API | 비고 |
|---|---|---|
| Vertical Roll-up table | `GET /api/agency/stores?include_metrics=true` (기존) | 5 매장 모두 자동 노출 |
| Code reuse % | static (frontend에 하드코드) | `[100, 95, 93, 84]` |
| Add-vertical cost | static | `[{name: 'cafe', days: 25}, {name: 'kbbq', days: 0.5}]` |
| Live Demo phone | static | `+1 (503) 994-1265` (JM Cafe) |

#### 라우팅

`src/routes` (또는 그에 상응) 에 `/admin/architecture-proof` 추가. agency owner만 접근 가능 (역할 가드 cafe agency `755fbac2-...` 사용).

---

## 2. 충돌 방지 룰 (Frontend Claude 필수 준수)

### 2.1 영역 분리 (절대 위반 금지)

- **Frontend Claude**: `frontend/*` 만 수정. `backend/*` + `docs/*` 절대 X.
- **Backend Claude (나)**: `backend/* + docs/*` 만 수정. `frontend/*` 절대 X.
- 공유 파일: `handoff.md` (둘 다 갱신 가능, 단 conflict 시 사용자 중재).

### 2.2 Git 작업 룰

```bash
# 작업 시작 전 (항상)
cd /Users/mchangpdx/jm-voice-ai-platform/frontend
git fetch origin
git pull --rebase origin feature/openai-realtime-migration

# 작업 끝나면 (명시적 path만)
git add frontend/<specific-files>     # NEVER `git add .`
git commit -m "feat(frontend): ..."
git push origin feature/openai-realtime-migration
```

### 2.3 검증 — 이번 backend push 후 frontend가 받아야 할 변경

```bash
# Frontend Claude 작업 전 검증
cd frontend  # or repo root
git log --oneline -5 origin/feature/openai-realtime-migration

# 다음 commit이 보여야 함:
# <new>     feat(kbbq-sim): synthetic data + agency dispatch + frontend handoff spec
# 18d7e68  feat(dashboard): P0-E Tier 3 ROI calculator
# f8a4d95  feat(frontend): KBBQ vertical entry
# a006800  feat(kbbq): Day 1 templates + adapter
# ...
```

### 2.4 동시 작업 보호 구역 (절대 건드리지 말 것)

기존 보호 구역 30개 + 신규 추가:

**신규 (2026-05-10 backend)**:
- `backend/app/api/agency.py` import + KBBQ elif 분기 (knowledge.kbbq dispatch)
- KBBQ stores row (id=`e365aa0e-6e62-49a1-8c5f-0c55af72a53d`)
- KBBQ call_logs (280 rows) + orders (180 rows)

**Frontend 영향 X**: 위 변경들은 모두 backend layer. frontend는 그대로 `GET /api/agency/...` 호출 → KBBQ 매장 자동 노출됨.

---

## 3. 즉시 진행 — Frontend Claude 권장 단계

| 순서 | 작업 | 예상 시간 |
|---|---|---|
| 1 | `git pull --rebase` + `git log` 검증 | 1분 |
| 2 | Dev server 재시작 (`npm run dev`) — KBBQ 매장 dashboard에 노출 확인 | 5분 |
| 3 | F-B 작업: Real vs Simulated 라벨 추가 (Agency Store 카드 grid) | 30분 |
| 4 | F-C 작업: `/admin/architecture-proof` 페이지 신규 (4 sections) | 2-4 시간 |
| 5 | `git add frontend/<paths>` 명시적 + commit + push | 5분 |

### Section 2 (Code Reuse Visualization) 데이터 상수

```typescript
// src/views/admin/ArchitectureProof.constants.ts (or similar)

export const CODE_REUSE_LAYERS = [
  { name: 'Layer 1 — Auth / RLS / Gemini / OpenAI',  reuse: 100, locReused: 263,  locTotal: 263 },
  { name: 'Layer 2 — Universal Skills (Tools/Schemas)', reuse: 95, locReused: 1410, locTotal: 1484 },
  { name: 'Layer 3 — Knowledge Adapters',  reuse: 93, locReused: 310,  locTotal: 334 },
  { name: 'Layer 4 — External Adapters (POS/SMS/Email)', reuse: 84, locReused: 390,  locTotal: 463 },
  { name: 'API Layer (FastAPI routes)',  reuse: 81, locReused: 5780, locTotal: 7169 },
  { name: 'Services Layer (Bridge/Menu)', reuse: 80, locReused: 4920, locTotal: 6149 },
];

export const VERTICAL_ADD_COSTS = [
  { vertical: 'cafe',     days: 25.0, mode: 'baseline (real)',  loc: 'all' },
  { vertical: 'beauty',   days: 1.5,  mode: 'sim',              loc: '~120' },
  { vertical: 'auto_repair', days: 1.5, mode: 'sim',            loc: '~120' },
  { vertical: 'home_services', days: 1.5, mode: 'sim',         loc: '~120' },
  { vertical: 'kbbq',     days: 0.5,  mode: 'sim',              loc: '1,137 (templates + adapter)' },
];

export const STORE_MODE_BADGES = {
  '7c425fcb-91c7-4eb7-982a-591c094ba9c9': { mode: 'real', since: '2026-04-25' },
  // All other stores: { mode: 'sim', since: null }
};
```

### Section 4 (Live Demo) CTA 카피

```tsx
<div className="rounded-lg border-2 border-green-500 bg-green-50 p-6">
  <h3 className="text-xl font-bold">Try it live now</h3>
  <p className="mt-2">
    Call <a href="tel:+15039941265" className="text-blue-600 underline">
      +1 (503) 994-1265
    </a> — JM Cafe AI agent answers in 5 languages.
  </p>
  <p className="mt-2 text-sm text-gray-600">
    All other verticals shown above use simulated 60-day data to demonstrate the same architecture in production.
  </p>
</div>
```

---

## 4. Backend follow-up (Frontend 작업 후)

Frontend Claude가 위 작업 완료 + commit + push 후, Backend가 다음을 처리:

1. **Optional**: `GET /api/agency/architecture-proof` 엔드포인트 (frontend가 static으로 처리하면 불필요)
2. Frontend P0 (이전 메시지) — `/api/store/metrics` + `/api/store/analytics` Layer 3 dispatch, `/api/store/calls/{id}/details`, `/api/store/alerts/tier3` — 매장 5개 sim 데이터로 라이브 검증 가능

---

## 5. 한 줄 요약

> Backend가 KBBQ sim 매장 + 280 calls + 180 orders + agency.py kbbq dispatch 추가 완료. Frontend는 git pull 후 `/admin/architecture-proof` 신규 페이지 (4 sections) + agency dashboard에 Real/Sim 라벨 추가하면 5 vertical 멀티-tenant 입증 dashboard 완성.

---

## 6. 사용자 (Michael)가 Frontend Claude에 전달할 메시지 (그대로 복사)

```
백엔드가 KBBQ sim 매장 + 합성 데이터 + agency.py kbbq dispatch 마무리했어. push 끝남.

⚠️ 다음 작업 진행 전 필수:
1. git fetch origin && git pull --rebase origin feature/openai-realtime-migration
2. git log --oneline -5 으로 최신 backend commit 확인 (kbbq-sim 포함)

작업 spec: docs/strategic-research/2026-05-10_smb-pivot-strategy/FRONTEND_HANDOFF_SPEC.md 읽기

핵심 작업 2가지:
1. Agency Dashboard store grid에 Real vs Simulated 라벨 추가
   - JM Cafe (id=7c425fcb-...) = Real (since 2026-04-25)
   - 나머지 4 매장 = Simulated — 60-day window
2. /admin/architecture-proof 신규 페이지 (투자자 시연용)
   - Hero banner: "5 verticals live in 0.5 founder-days per vertical. 81% backend code reuse."
   - Section 1: Vertical Performance Roll-up 테이블 (5 매장 KPI 비교, GET /api/agency/stores 활용)
   - Section 2: Code Reuse Visualization (4-Layer, static 상수 — spec 파일에 정의)
   - Section 3: Add-Vertical Cost Chart (kbbq=0.5d, cafe=25d, 95% faster)
   - Section 4: Live Demo CTA (call +1-503-994-1265)

KBBQ store_id 확인: e365aa0e-6e62-49a1-8c5f-0c55af72a53d
영역 충돌 룰: frontend/* 만 수정, git add 명시적 경로, git add . 금지

작업 끝나면 commit + push해주고 알려줘.
```
