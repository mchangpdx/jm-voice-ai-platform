// Architecture-proof page constants (per FRONTEND_HANDOFF_SPEC 2026-05-10)
// (아키텍처 입증 페이지 상수 — backend handoff spec과 1:1 일치)

export type StoreMode = 'real' | 'sim'

export interface StoreModeBadge {
  mode: StoreMode
  since: string | null
}

// JM Cafe is the only real store; all others run on synthetic 60-day data
// (JM Cafe만 실 매장. 나머지는 60일 합성 데이터로 동일 아키텍처 입증)
export const STORE_MODE_BADGES: Record<string, StoreModeBadge> = {
  '7c425fcb-91c7-4eb7-982a-591c094ba9c9': { mode: 'real', since: '2026-04-25' },
}

export function getStoreMode(storeId: string): StoreModeBadge {
  return STORE_MODE_BADGES[storeId] ?? { mode: 'sim', since: null }
}

export interface CodeReuseLayer {
  name:      string
  reuse:     number  // percent
  locReused: number
  locTotal:  number
}

export const CODE_REUSE_LAYERS: CodeReuseLayer[] = [
  { name: 'Layer 1 — Auth / RLS / Gemini / OpenAI',          reuse: 100, locReused:  263, locTotal:  263 },
  { name: 'Layer 2 — Universal Skills (Tools/Schemas)',      reuse:  95, locReused: 1410, locTotal: 1484 },
  { name: 'Layer 3 — Knowledge Adapters',                    reuse:  93, locReused:  310, locTotal:  334 },
  { name: 'Layer 4 — External Adapters (POS/SMS/Email)',     reuse:  84, locReused:  390, locTotal:  463 },
  { name: 'API Layer (FastAPI routes)',                      reuse:  81, locReused: 5780, locTotal: 7169 },
  { name: 'Services Layer (Bridge / Menu)',                  reuse:  80, locReused: 4920, locTotal: 6149 },
]

export interface VerticalAddCost {
  vertical: string
  days:     number
  mode:     string
  loc:      string
}

export const VERTICAL_ADD_COSTS: VerticalAddCost[] = [
  { vertical: 'cafe',          days: 25.0, mode: 'baseline (real)', loc: 'all'                          },
  { vertical: 'beauty',        days:  1.5, mode: 'sim',             loc: '~120'                         },
  { vertical: 'auto_repair',   days:  1.5, mode: 'sim',             loc: '~120'                         },
  { vertical: 'home_services', days:  1.5, mode: 'sim',             loc: '~120'                         },
  { vertical: 'kbbq',          days:  0.5, mode: 'sim',             loc: '1,137 (templates + adapter)'  },
]

export const LIVE_DEMO_PHONE      = '+1 (503) 994-1265'
export const LIVE_DEMO_TEL_HREF   = 'tel:+15039941265'
export const LIVE_DEMO_STORE_NAME = 'JM Cafe'

// ─────────────────────────────────────────────────────────────────────────
// Architecture diagram — 4 layers + cross-cutting concerns
// (4계층 도식 — 각 layer의 역할 + 재사용 강도)
// ─────────────────────────────────────────────────────────────────────────

export interface ArchitectureLayer {
  id:          string           // anchor + svg group id
  num:         number           // 1..4
  name:        string
  role:        string           // one-line responsibility
  examples:    string[]         // 2–3 module names
  reusePct:    number           // matches CODE_REUSE_LAYERS
  color:       string           // hex
}

export const ARCHITECTURE_LAYERS: ArchitectureLayer[] = [
  {
    id: 'layer-1', num: 1, name: 'Core',
    role: 'Auth / RLS / LLM clients — every request enters here',
    examples: ['auth.py', 'rls_session', 'gemini_client', 'openai_realtime'],
    reusePct: 100, color: '#1e3a8a',
  },
  {
    id: 'layer-2', num: 2, name: 'Universal Skills',
    role: '7 shared agent tools — same JSON schema across verticals',
    examples: ['create_order', 'modify_reservation', 'recall_order'],
    reusePct: 95, color: '#2563eb',
  },
  {
    id: 'layer-3', num: 3, name: 'Knowledge Adapters',
    role: 'Vertical-specific KPI + business logic — thin glue per industry',
    examples: ['restaurant', 'kbbq', 'beauty', 'auto_repair'],
    reusePct: 93, color: '#0891b2',
  },
  {
    id: 'layer-4', num: 4, name: 'External Bridges',
    role: 'POS / SMS / Email relays — fire-and-forget asynchronous',
    examples: ['loyverse_bridge', 'twilio_sms', 'resend_email'],
    reusePct: 84, color: '#16a34a',
  },
]

// ─────────────────────────────────────────────────────────────────────────
// Competitive comparison — JM vs Maple / Yelp Agent / Slang.ai
// All scored 0..10 (per memory rule score_table_rule — show per-item + total)
// Sources: competitive_maple_baseline.md (2026-05-02), public pricing pages.
// (10점 만점 항목별 + 합계 — 메모리 룰 score_table_rule 준수)
// ─────────────────────────────────────────────────────────────────────────

export interface CompetitiveCriterion {
  key:    string
  label:  string
  weight: number   // 1..3 (visual emphasis, not multiplier)
}

export const COMPETITIVE_CRITERIA: CompetitiveCriterion[] = [
  { key: 'vertical_depth', label: 'Vertical coverage (SMB verticals supported)', weight: 3 },
  { key: 'multilingual',   label: 'Multilingual native (5+ languages)',          weight: 3 },
  { key: 'pos_integration',label: 'Deep POS integration (live order push)',      weight: 3 },
  { key: 'order_lifecycle',label: 'Order lifecycle (create/modify/cancel)',      weight: 2 },
  { key: 'reservation',    label: 'Reservation + recall + modify',                weight: 2 },
  { key: 'audit_log',      label: 'Tamper-proof audit log',                       weight: 2 },
  { key: 'time_to_add',    label: 'Time to onboard new vertical',                 weight: 2 },
  { key: 'price',          label: 'Per-store price (lower = better)',             weight: 1 },
  { key: 'self_serve',     label: 'Self-serve onboarding wizard',                 weight: 1 },
  { key: 'observability',  label: 'Operator dashboard + system health',           weight: 1 },
]

export interface CompetitiveCompetitor {
  id:     string
  name:   string
  color:  string
  scores: Record<string, number>   // key → 0..10
}

export const COMPETITIVE_COMPETITORS: CompetitiveCompetitor[] = [
  {
    id: 'jm', name: 'JM Voice', color: '#4338ca',
    scores: {
      vertical_depth: 9, multilingual: 10, pos_integration: 9, order_lifecycle: 10,
      reservation: 9, audit_log: 10, time_to_add: 10, price: 9, self_serve: 9, observability: 9,
    },
  },
  {
    id: 'maple', name: 'Maple Inc.', color: '#dc2626',
    scores: {
      vertical_depth: 6, multilingual: 4, pos_integration: 5, order_lifecycle: 6,
      reservation: 5, audit_log: 4, time_to_add: 4, price: 5, self_serve: 6, observability: 5,
    },
  },
  {
    id: 'yelp', name: 'Yelp Agent', color: '#f59e0b',
    scores: {
      vertical_depth: 4, multilingual: 3, pos_integration: 3, order_lifecycle: 4,
      reservation: 7, audit_log: 3, time_to_add: 3, price: 4, self_serve: 5, observability: 4,
    },
  },
  {
    id: 'slang', name: 'Slang.ai', color: '#0891b2',
    scores: {
      vertical_depth: 5, multilingual: 3, pos_integration: 4, order_lifecycle: 5,
      reservation: 8, audit_log: 4, time_to_add: 3, price: 4, self_serve: 7, observability: 6,
    },
  },
]

// ─────────────────────────────────────────────────────────────────────────
// ROI Calculator defaults — pessimistic SMB baseline.
// User can override via sliders in the UI. Output = monthly + annual savings.
// (보수적인 SMB 기본값 — UI 슬라이더로 재정의 가능)
// ─────────────────────────────────────────────────────────────────────────

export interface RoiDefaults {
  callsPerMonth:    number     // inbound calls/month
  avgTicketUsd:     number     // average ticket size on a successful call
  conversionRatePct: number    // % of calls that convert to revenue
  staffHourlyUsd:   number     // hourly wage for staff that would otherwise answer
  minutesPerCall:   number     // staff time freed per call
  jmMonthlyUsd:     number     // JM subscription
}

export const ROI_DEFAULTS: RoiDefaults = {
  callsPerMonth:     400,
  avgTicketUsd:      28,
  conversionRatePct: 35,
  staffHourlyUsd:    20,
  minutesPerCall:    3,
  jmMonthlyUsd:      199,
}

// ─────────────────────────────────────────────────────────────────────────
// KPI hero — three top-line numbers with units + sublabel.
// Verticals + reuse % derive from existing arrays; time-to-add is fastest add.
// (히어로 3대 KPI — verticals / reuse % / fastest time-to-add)
// ─────────────────────────────────────────────────────────────────────────

export interface HeroKpiData {
  verticals:       number    // count of verticals (= CODE_REUSE_LAYERS not used; derived elsewhere)
  reusePct:        number    // overall code reuse %
  timeToAddDays:   number    // fastest vertical add
}

